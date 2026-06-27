# mvw

A command-line tool for searching and downloading content from
[MediathekViewWeb](https://mediathekviewweb.de/) (MVW), the index of German
public-broadcasting media libraries (ARD, ZDF, WDR, and more). Built for
automation: the headline feature is reliable, Plex-friendly **season**
downloads.

## Install

Requires Python ≥ 3.13. The distribution is published as **`mvw-cli`** (the
PyPI name `mvw` was already taken); the installed command is `mvw`.

Install as a standalone tool with [uv](https://github.com/astral-sh/uv):

```bash
uv tool install mvw-cli      # adds the `mvw` command to your PATH
```

Or run it once without installing:

```bash
uvx --from mvw-cli mvw search "#Tatort"
```

With pip:

```bash
pip install mvw-cli
```

> **Note:** HLS (`.m3u8`) downloads require [ffmpeg](https://ffmpeg.org/download.html)
> on your `PATH`. It is an external (non-Python) dependency and is not installed
> automatically.

### From source

```bash
uv sync                      # create the dev environment
uv run mvw --help            # run from the working tree
```

## Query grammar

The query string follows the MediathekViewWeb syntax:

| Prefix | Field searched | Example |
|--------|---------------|---------|
| `!` | channel | `!ARD` |
| `#` | topic | `#Tatort` |
| `+` | title | `+Schokolade` |
| `*` | description | `*Berlin` |
| (none) | topic and title | `feuer flamme` |
| `>N` | duration > N minutes | `>80` |
| `<N` | duration < N minutes | `<10` |

Combination rules:

- **Space between different selectors** → AND: `!WDR #Tatort` means channel=WDR
  AND topic=Tatort.
- **Same selector repeated** → OR: `!ARD !ZDF` means ARD or ZDF.
- **Comma within a selector's value** → AND of words: `#Olympia,Tokio` matches
  topic containing both "Olympia" and "Tokio".
- **No negation operator.** Exclusion is done client-side with `--exclude`.

> Note: the API is case-insensitive and flexible with umlauts
> (`ö` ≈ `oe` ≈ `OE`).

## Commands

### `mvw search`

Search MVW and display a Rich results table.

```
mvw search QUERY
           [--channel C] [--topic T] [--title T] [--description D]
           [--min-duration MIN] [--max-duration MAX]
           [--sort timestamp|duration|channel] [--order asc|desc]
           [--future] [--limit N] [--offset N] [--json]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--channel` | — | Filter by channel (structured flag, not query syntax) |
| `--topic` | — | Filter by topic |
| `--title` | — | Filter by title |
| `--description` | — | Filter by description |
| `--min-duration` | — | Minimum duration in minutes |
| `--max-duration` | — | Maximum duration in minutes |
| `--sort` | `timestamp` | Sort field |
| `--order` | `desc` | Sort order (`asc` or `desc`) |
| `--future` | off | Include not-yet-aired entries |
| `--limit` | 15 | Number of results to fetch |
| `--offset` | 0 | Pagination offset |
| `--json` | off | Emit raw JSON to stdout (scripting-friendly) |

Example:

```bash
mvw search "#Tatort !ARD >80"
```

### `mvw download`

Search and download matching entries. Run `--dry-run` first to preview the
exact file tree before downloading anything.

```
mvw download QUERY
             [--channel C] [--topic T] [--title T]
             [--min-duration MIN] [--max-duration MAX]
             [--season] [--dry-run]
             [--resolution low|medium|high|best]
             [--output DIR] [-o DIR] [--template STR]
             [--exclude TERM ...] [--dedup] [--latest-season]
             [--season-number N] [--subtitles] [--limit N]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--channel` | — | Filter by channel |
| `--topic` | — | Filter by topic |
| `--title` | — | Filter by title |
| `--min-duration` | — | Minimum duration in minutes |
| `--max-duration` | — | Maximum duration in minutes |
| `--season` | off | Group into Plex season folders using `S##E##` numbering |
| `--dry-run` | off | Preview the file tree and source URLs; download nothing |
| `--resolution` | `best` | Resolution preference: `low`, `medium`, `high`, or `best` |
| `--output`, `-o` | config default | Output directory |
| `--template` | Plex default | Custom filename template (see below) |
| `--exclude` | — | Regex to exclude entries from title/topic/description (repeatable) |
| `--dedup` | off | Remove near-duplicate entries, keeping the highest-quality copy |
| `--latest-season` | off | Keep only entries from the highest detected season |
| `--season-number` | — | Override detected season number |
| `--subtitles` | off | Also fetch subtitle files alongside each video |
| `--limit` | 200 | Maximum number of entries to resolve |
| `--force` | off | Redownload every matched entry even if a valid file already exists |

#### Download behavior and verification

By default, `download` checks each target path before fetching:

- a file whose size matches the catalog's expected byte size is **skipped**
  (`✓ … already exists, skipped`);
- a file whose size does **not** match (truncated/corrupt from an interrupted
  run) is deleted and **redownloaded** (`⚠ … corrupted (size mismatch),
  redownloading`);
- HLS (`.m3u8`) targets have no reliable size, so any non-empty existing file
  is treated as complete.

Each fresh download is verified against the server's `Content-Length` (falling
back to the catalog size) before the temporary `.part` file is promoted to its
final name, so an interrupted transfer never leaves a corrupt final file. A run
ends with a summary line, e.g. `Done: 8 downloaded, 5 skipped, 2 redownloaded,
1 failed`.

#### Filename template

The default template produces Plex/Jellyfin-compatible paths:

```
{series} ({year})/Season {s:02d}/{series} ({year}) - s{s:02d}e{e:02d} - {ep_title} [{res}].{ext}
```

Override with `--template`. Available tokens:

| Token | Value |
|-------|-------|
| `{series}` | Topic (show name) |
| `{year}` | Broadcast year |
| `{s}` | Season number (supports `:02d` formatting) |
| `{e}` | Episode number (supports `:02d` formatting) |
| `{ep_title}` | Cleaned episode title |
| `{res}` | Resolution label (see note below) |
| `{channel}` | Broadcaster |
| `{date}` | Broadcast date (`YYYY-MM-DD`) |
| `{ext}` | File extension |

**`{res}` label note:** MVW exposes only three tiers (`low` / `medium` / `high`),
not measured pixel heights. The `{res}` token maps these to conventional labels —
`high → "1080p"`, `medium → "720p"`, `low → "480p"` — because Plex parses these
and they reflect typical public-broadcast encodes. These are labels, not
guarantees of exact resolution.

#### ffmpeg requirement for HLS

Some entries serve `.m3u8` HLS playlists instead of direct `.mp4` files. Those
are downloaded via `ffmpeg -i <url> -c copy <dest>`. If ffmpeg is not on your
PATH and an HLS entry is encountered, `mvw` exits with code 4 and prints an
install hint. Install from <https://ffmpeg.org/download.html>.

#### Flagship example: Feuer und Flamme

```bash
# Preview the newest season, no audio description, deduped
mvw download "#Feuer und Flamme" --season --latest-season --dedup \
    --exclude Audiodeskription --exclude "Gebärdensprache" \
    --output ~/Media/TV --dry-run

# Then download for real in best resolution
mvw download "#Feuer und Flamme" --season --latest-season --dedup \
    --exclude Audiodeskription --output ~/Media/TV
```

### `mvw info`

Show a Rich detail panel for the first match of a query.

```
mvw info QUERY
```

Displays: topic, title, description, channel, aired datetime, duration, size,
available resolutions with URLs, subtitle URL, website URL, and detected
season/episode.

### `mvw config`

Manage persistent configuration stored in `config.toml`
(location: `platformdirs.user_config_dir("mvw")`).

```
mvw config show              # Print the effective config (key = value)
mvw config set KEY VALUE     # Write a key to config.toml
mvw config path              # Print the path to config.toml
```

Available keys: `download_dir`, `template`, `resolution`, `user_agent`,
`page_size`, `request_timeout`.

CLI flags always override config file values, which override built-in defaults.

## Exit codes

| Code | Condition |
|------|-----------|
| 0 | Success or no results |
| 2 | API error (non-null `err`), HTTP error, or network/timeout after retries |
| 4 | HLS entry encountered but ffmpeg is not installed |
| 5 | Partial/interrupted download failure |

## Releasing

Cutting a release is one command. It verifies the tree is clean and in sync,
runs the tests, bumps the version, commits, tags, and pushes — and the pushed
tag triggers the GitHub Actions workflow that publishes to PyPI via Trusted
Publishing.

```bash
scripts/release.sh            # patch bump (default): 0.1.0 → 0.1.1
scripts/release.sh minor      # 0.1.0 → 0.2.0
scripts/release.sh major      # 0.1.0 → 1.0.0
```

## Running tests

```bash
# Unit and mocked tests (default)
uv run pytest -q

# Include the live API test (requires network access)
uv run pytest -m live tests/test_live.py -v
```
