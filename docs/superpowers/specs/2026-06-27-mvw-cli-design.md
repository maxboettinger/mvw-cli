# MVW CLI — Design Spec

**Date:** 2026-06-27
**Status:** Approved (pending written-spec review)

A Python CLI for searching and downloading content from
[MediathekViewWeb](https://mediathekviewweb.de/) (MVW), the index of German
public-broadcasting media libraries. Built for automation: the headline feature
is reliable, Plex-friendly **season** downloads.

---

## 1. Goals & non-goals

### Goals
- Ergonomic, modular CLI (Typer + Rich) modeled on the structure of Simon
  Willison's `llm` tool: a thin command layer over focused modules.
- Search MVW with both a raw query string and structured flags.
- Download single entries **and** whole "seasons" of a series.
- Produce Plex/Jellyfin-parseable file/folder names by default, with a custom
  template override.
- Client-side filtering (exclude Audiodeskription/Gebärden/Hörfassung, dedup
  near-duplicate titles, keep only the latest season).
- Highest-resolution-with-fallback downloads, resume support, HLS handling.

### Non-goals (YAGNI)
- No saved-search profiles / templates persisted per name (filter flags only).
- No interactive TUI app (Rich rendering only, not Textual).
- No transcoding beyond what ffmpeg does to mux HLS into a container.
- No account/login (MVW API is anonymous).

---

## 2. Decisions (locked)

| Area | Decision |
|------|----------|
| UI stack | **Typer + Rich** (Typer = command tree on top of Click; Rich = tables/progress/spinners/panels) |
| Download engine | **httpx** for direct MP4 (async, Range/resume, progress) + **ffmpeg** fallback for `.m3u8` HLS |
| Episode numbering | **Regex-parse the title**, fall back to broadcast-date order; season = year when no pattern found |
| Filtering | **Filter flags only** — no named saved searches |
| Naming | **Plex/TRaSH default** layout + `--template` override |
| Resolution | **Highest available, fallback down**; `--resolution low\|medium\|high\|best` overrides |
| Selection | **Query-driven, non-interactive** default; `--dry-run` preview and `-i` interactive picker available; `search`→`download <id>` also supported |

---

## 3. MediathekViewWeb API reference

**Endpoint:** `POST https://mediathekviewweb.de/api/query`

**Headers:**
- `Content-Type: text/plain` (required — sending `application/json` triggers a
  server-side JSON parse error)
- `User-Agent: <configurable>` (recommended)

**Request body** (JSON, sent as a text/plain string):
```json
{
  "queries": [
    { "fields": ["topic", "title"], "query": "feuer und flamme" },
    { "fields": ["channel"], "query": "wdr" }
  ],
  "sortBy": "timestamp",
  "sortOrder": "desc",
  "future": false,
  "offset": 0,
  "size": 15,
  "duration_min": 1200,
  "duration_max": 7200
}
```
- `fields` valid values: `channel`, `topic`, `title`, `description`.
- `duration_min` / `duration_max` are in **seconds**.
- `future`: include not-yet-aired entries.
- `size` accepts up to ~100 per request; paginate with `offset`.

**Response body:**
```json
{
  "result": {
    "results": [
      {
        "channel": "WDR",
        "topic": "Feuer und Flamme",
        "title": "Feuer und Flamme (S07/E05)",
        "description": "...",
        "timestamp": 1568707200,
        "duration": 2700,
        "size": 1234567890,
        "url_website": "https://...",
        "url_subtitle": "https://....xml",
        "url_video": "https://....mp4",
        "url_video_low": "https://....mp4",
        "url_video_hd": "https://....mp4",
        "filmlisteTimestamp": "1568800000",
        "id": "..."
      }
    ],
    "queryInfo": {
      "filmlisteTimestamp": "1568800000",
      "resultCount": 15,
      "searchEngineTime": "12.34",
      "totalResults": 342
    }
  },
  "err": null
}
```
- `timestamp` is Unix epoch seconds; `duration` seconds; `size` bytes.
- Any of `url_video_low` / `url_video_hd` may be empty strings.
- Some `url_video*` values are `.m3u8` HLS playlists rather than `.mp4`.
- On error the top-level `err` is non-null (array of messages); handle it.

### Query-string syntax (the translate layer must reproduce this)
| Prefix | Field | Example |
|--------|-------|---------|
| `!` | channel | `!ARD` |
| `#` | topic | `#Tatort` |
| `+` | title | `+Schokolade` |
| `*` | description | `*Berlin` |
| (none) | topic **and** title | `feuer flamme` |
| `>N` | duration > N **minutes** | `>80` |
| `<N` | duration < N **minutes** | `<10` |

Combination rules:
- Space between **different** selectors → AND.
- The **same** selector repeated → OR (`!ARD !ZDF` = ARD or ZDF).
- Comma **within** a selector's value → AND of words (`#Olympia,Tokio`).
- Case-insensitive; umlauts flexible (`ö` ≈ `oe` ≈ `OE`).

> **No negation operator exists.** Exclusion (`--exclude`) is implemented
> client-side in `filters.py`, never in the API query.

---

## 4. Architecture

Thin command layer (`cli.py`) over focused, independently-testable modules.

```
src/mvw/
  __init__.py
  cli.py        # Typer app + command definitions; delegates to modules
  api.py        # HTTP client: query(payload) -> QueryResult; pagination helpers
  query.py      # translate layer: raw string OR flags -> queries[] payload
  models.py     # MediathekResult dataclass + humanizers (duration/size/date)
  filters.py    # exclude / dedup / latest-season (client-side)
  episodes.py   # regex S/E parsing, date-order fallback, season grouping
  naming.py     # Plex default + template renderer + filesystem sanitizing
  download.py   # httpx downloader (resume/Range + progress) + ffmpeg HLS
  display.py    # Rich tables, detail panels, progress bars, spinners
  config.py     # config.toml defaults via platformdirs
tests/
  ...           # pytest; respx-mocked HTTP; recorded fixtures; live tests behind a marker
```

### Module contracts

- **`api.py`**
  - `MediathekClient(user_agent, timeout, retries)`
  - `.query(payload: QueryPayload) -> QueryResult` — single POST.
  - `.iter_all(payload, page_size, cap) -> Iterator[MediathekResult]` —
    paginates via `offset` until `totalResults` or `cap` reached.
  - Depends on: `httpx`, `models`.

- **`query.py`**
  - `build_payload(raw: str | None, *, channel, topic, title, description,
    min_duration, max_duration, sort_by, sort_order, future, offset, size)
    -> QueryPayload`
  - `parse_raw(raw: str) -> list[QueryField]` reproduces the prefix grammar
    (`! # + *`, no-prefix, `> <` minutes→seconds, space/OR/comma rules).
  - Pure functions; no I/O. Depends on: `models`.

- **`models.py`**
  - `MediathekResult` dataclass mirroring a result row, plus:
    `aired: datetime`, `duration_human`, `size_human`,
    `video_url(resolution) -> str | None` (with fallback chain).
  - `QueryPayload`, `QueryResult`, `QueryInfo` dataclasses.
  - No I/O.

- **`filters.py`** (all pure, operate on `list[MediathekResult]`)
  - `exclude(results, patterns) -> results` (regex over title/topic/desc).
  - `dedup(results) -> results` — normalize title (strip
    `(Audiodeskription)`, `mit Gebärdensprache`, `Hörfassung`, punctuation,
    case, whitespace); group near-duplicates (normalized key + `difflib`
    ratio threshold); keep best (highest res, then longest duration).
  - `latest_season(results) -> results` — keep only entries whose detected
    season equals the max detected season.

- **`episodes.py`**
  - `parse_se(title) -> (season:int|None, episode:int|None)` via ordered
    regexes: `S(\d{1,2})[ _/-]?E(\d{1,3})`, `Staffel\s*(\d+).*?Folge\s*(\d+)`,
    `Folge\s*(\d+)`, `(\d+)\.\s*Folge`, trailing `\((\d{1,3})\)`.
  - `assign(results, *, season_override) -> list[Episode]` — fills missing
    season with broadcast year, missing episode with timestamp-ascending order
    within its season. Returns rows enriched with `(season, episode)`.
  - `group_by_season(episodes) -> dict[int, list[Episode]]`.

- **`naming.py`**
  - `DEFAULT_TEMPLATE` →
    `"{series} ({year})/Season {s:02d}/{series} ({year}) - s{s:02d}e{e:02d} - {ep_title} [{res}].{ext}"`
  - `render(episode, template, resolution, ext) -> Path` with tokens
    `{series} {year} {s} {e} {ep_title} {res} {channel} {date} {ext}`.
  - **`{res}` note:** MVW exposes only three *tiers* (low / video / hd), not a
    pixel height. The `{res}` token renders a conventional label via a fixed
    map — `hd → "1080p"`, `medium/video → "720p"`, `low → "480p"` — chosen
    because Plex parses these and they reflect typical public-broadcast
    encodes. These are labels, not guarantees of exact resolution.
  - `sanitize(component) -> str` — strip/replace filesystem-illegal chars,
    collapse whitespace, trim length.

- **`download.py`**
  - `download(url, dest, *, progress, resume=True) -> Path` — httpx streaming
    with HTTP Range resume; routes `.m3u8` URLs to `download_hls` (ffmpeg).
  - `download_hls(url, dest, *, progress) -> Path` — shell out to ffmpeg
    (`-i url -c copy dest`), parse progress; raise typed error if ffmpeg
    missing.
  - `pick_resolution(result, preference) -> (url, res_label)`.

- **`display.py`** — Rich rendering only (results table, detail panel,
  dry-run file tree, progress group, spinners, error panels). No business logic.

- **`config.py`** — load/merge `config.toml`
  (`platformdirs.user_config_dir("mvw")`): `download_dir`, `template`,
  `resolution`, `user_agent`, `page_size`, `request_timeout`. CLI flags always
  override file values, which override built-in defaults.

---

## 5. Commands & UX

```
mvw search   QUERY [--channel C] [--topic T] [--title T] [--description D]
                   [--min-duration MIN] [--max-duration MIN]
                   [--sort timestamp|duration|channel] [--order asc|desc]
                   [--future] [--limit N] [--offset N] [--json]

mvw download QUERY [--season] [--dry-run] [--interactive/-i]
                   [--resolution low|medium|high|best]
                   [--output DIR] [--template STR]
                   [--exclude TERM ...] [--dedup] [--latest-season]
                   [--season-number N] [--subtitles] [--limit N]

mvw info     ID | QUERY        # Rich detail panel for one entry

mvw config   show | set KEY VALUE | path
```

### `search`
- Rich table: `#`, channel, topic, title, date, duration, resolution badges
  (LOW/SD/HD present).
- Footer: `showing 1–15 of 342 · 12.3 ms`.
- Interactive paging when stdout is a TTY and `--json` not set: prompt
  `n`ext / `p`rev / number→`info` / `q`uit. Non-TTY prints the first
  `--limit` rows and exits (scripting-friendly).
- `--json` emits raw structured results to stdout, nothing else.

### `download` (default: query-driven, non-interactive)
Pipeline: `query.build_payload` → `api.iter_all` → `filters.exclude` →
`filters.dedup` (if `--dedup`) → `filters.latest_season` (if `--latest-season`)
→ `episodes.assign`/`group_by_season` (if `--season`) → `naming.render` →
`download.download`.

- Default downloads every (filtered) match. `--season` enables season grouping
  and Plex foldering; without it, files use the same template but a flat target.
- `--dry-run`: render the **exact** resulting file tree (Rich tree) and the
  source URL/resolution per file; download nothing. Always recommend running
  this first in docs.
- `-i`: Rich checkbox-style picker over the resolved set before downloading.
- Resolution: `best` (default) = hd→video→low fallback chain.
- Progress: a Rich `Progress` group — one overall task (e.g. "Season 07:
  3/8 files") plus the active file's byte-progress bar; spinner during the
  initial query/pagination.
- `--subtitles`: also fetch `url_subtitle` next to the video
  (`<same stem>.<ext>`).

### `info`
Rich panel: full topic/title/description, channel, aired datetime, duration,
size, available resolutions with URLs, subtitle URL, website URL,
detected/synthesized season+episode.

### `config`
`show` prints effective config + source; `set KEY VALUE` writes the toml;
`path` prints the file location.

---

## 6. Errors & exit codes

Typed exceptions in a small hierarchy → friendly Rich error panels; never raw
tracebacks for expected failures.

| Condition | Behavior | Exit |
|-----------|----------|------|
| Success | — | 0 |
| No results | Message, no error panel | 0 |
| API `err` non-null / HTTP error | Error panel with server message | 2 |
| Network/timeout (after retries) | Error panel | 3 |
| HLS entry but ffmpeg missing | Error panel with install hint | 4 |
| Partial/interrupted download | Resume on rerun; on hard fail, keep `.part` and report | 5 |
| Bad usage (Typer) | Typer's usage error | 2 |

---

## 7. Testing strategy (TDD)

- **Unit (no network):**
  - `query`: raw-string grammar → payload; flags → payload; minutes→seconds.
  - `episodes`: each regex pattern; date-order fallback; season override.
  - `naming`: default template; custom template; sanitization edge cases.
  - `filters`: exclude regex; dedup keeps best copy; latest-season selection.
  - `models`: humanizers; resolution fallback chain.
- **HTTP (mocked via `respx`):** `api.query` request shape (text/plain body,
  headers), response parsing, `err` handling, `iter_all` pagination.
- **download:** mocked httpx streaming with a `Range` resume case; ffmpeg
  branch via a fake/stubbed subprocess.
- **Fixtures:** at least one recorded real API response committed under
  `tests/fixtures/`.
- **Live tests:** behind a `@pytest.mark.live` marker, opt-in only.

---

## 8. Dependencies

`typer`, `rich`, `httpx`, `platformdirs`. Dev: `pytest`, `respx`.
External runtime (optional, for HLS only): `ffmpeg` on PATH.
Python ≥ 3.13 (per existing `pyproject.toml`).

---

## 9. Open follow-ups (not blocking)

- Confirm console-command name `mvw` vs. repo name `or-cli`.
- Validate exact `.m3u8` vs `.mp4` distribution in real responses during
  implementation (drives how often the ffmpeg path is exercised).
