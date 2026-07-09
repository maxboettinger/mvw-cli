# Noridoc: mvw package

Path: @/src/mvw

### Overview

- The entire implementation of the `mvw` CLI: a Typer app that queries the MediathekViewWeb (MVW) API for German public-broadcasting media and downloads results, optionally arranged into Plex-style season folders.
- Organized as a thin pipeline: query building → API client → episode/season inference → filename rendering → download, with `cli.py` as the orchestrator and `display.py` for all Rich-based terminal output.
- Ships as `mvw-cli` on PyPI (console scripts `mvw` and `mvw-cli`); published via the release workflow described in @/docs.md.

### How it fits into the larger codebase

- @/src/mvw/cli.py is the only entry point (`mvw = "mvw.cli:app"` in @/pyproject.toml). It composes every other module in this package and is the sole place that decides process exit codes.
- @/tests exercises this package exclusively through mocks: `respx` intercepts httpx traffic used by @/src/mvw/api.py and @/src/mvw/download.py, and POSIX shell scripts stand in for `ffmpeg`. No test hits the real MVW API except the one marked `live` (excluded by default via `addopts = "-m 'not live'"` in @/pyproject.toml).
- CLI tests monkeypatch module-level names on `cli` — `cli._make_client`, `cli.download_file`, `cli.download_hls`, `cli.remote_size` — rather than reaching into `api.py`/`download.py` directly. These names are effectively a test seam; renaming or inlining them at the call site in `cli.py` breaks the test suite even if behavior is unchanged.
- Only external dependency is the MediathekViewWeb API (`https://mediathekviewweb.de/api/query`) reached via `httpx`, plus an optional `ffmpeg` binary on `PATH` for HLS (`.m3u8`) sources.

### Core Implementation

- **Query grammar → API payload**: @/src/mvw/query.py's `parse_raw` turns the `!channel #topic +title *description >min <max` string grammar into MVW query dicts; `build_payload` merges that with the `search`/`download` command's discrete `--channel`/`--topic`/etc. flags and sort/pagination fields consumed by @/src/mvw/api.py.
- **API client**: `MediathekClient.query` (@/src/mvw/api.py) POSTs JSON with `Content-Type: text/plain` — a quirk of the MVW API, not a bug — and retries both transport errors and 5xx responses with exponential backoff (`backoff_base * 2**(attempt-1)`) before raising `MediathekError`; other non-200 statuses and non-JSON 200 bodies raise immediately without retry. `iter_all` paginates by re-issuing `query` with advancing offsets until `cap` or `total_results` is reached.
- **Episode/season inference**: @/src/mvw/episodes.py's `parse_se` recognizes several German season/episode title conventions (`S07E05`, `Staffel 7 ... Folge 5`, bare `Folge N`, trailing `(N)`); `assign` resolves a season for every row (falling back to the broadcast year, or season `0` — Plex's "Specials" — when there is no parsed season and no usable timestamp) and numbers undated/unnumbered episodes sequentially per season by broadcast timestamp, skipping numbers already taken by explicitly-parsed episodes.
- **Filename rendering**: @/src/mvw/naming.py's `render` fills the `{series}/{year}/.../s{s:02d}e{e:02d}...` template (or a user-supplied one) from an `Episode`, sanitizing each path component against traversal/illegal characters; unknown tokens or bad format specs raise `TemplateError` with the list of valid tokens. `subtitle_dest` derives the sidecar subtitle path from the video destination and the subtitle URL's suffix (falling back to `.ttml`, the format actually served).
- **Download plan and execution**: `cli.download` (@/src/mvw/cli.py) builds an ordered list of `(dest, url, tier, subtitle_url)` tuples — resolving each entry's URL via `pick_resolution` (@/src/mvw/download.py, which walks a tier fallback order defined in @/src/mvw/models.py's `resolve_video`) and rejecting entries with no usable video URL. Duplicate destination paths within one plan are skipped with a warning suggesting `--dedup` rather than being silently overwritten. `_run_downloads` then drives either `download` (plain HTTP, resumable via `.part` staging and Range requests) or `download_hls` (ffmpeg subprocess muxing HLS to `.part`) for each entry, rendering a two-tier Rich `Progress` (files overall, bytes per file).
- **Skip-existing oracle**: before downloading a non-forced entry, `remote_size` (@/src/mvw/download.py) HEAD-probes (falling back to a 1-byte ranged GET) the remote size without downloading the body; `verify_size` compares that to the on-disk file (or, for HLS/unknown sizes, just checks non-empty) to decide whether to skip, redownload as corrupt, or proceed.
- **Config**: @/src/mvw/config.py loads TOML from `platformdirs.user_config_dir("mvw")/config.toml`, layered over `DEFAULTS`; `set_value` validates keys against `DEFAULTS` and coerces typed values (int/float/bool), raising `ConfigError` (a user-facing message) on anything invalid. The CLI additionally validates the resolved `--resolution`/config value against the `Resolution` enum, since config values are free text where the flag is enum-checked by Typer.
- **Filtering/dedup**: @/src/mvw/filters.py's `compile_patterns` validates `--exclude` regexes up front (before any network round trip) so bad patterns fail fast with a friendly message; `dedup` collapses same-topic/normalized-title entries to the highest-resolution/longest copy, `latest_season` keeps only rows whose parsed season equals the max seen.

### Things to Know

- Every user-facing error path in `cli.py` funnels through `display.error_panel` on stderr and a specific `typer.Exit` code: `0` success/no results, `2` invalid input/config or API/network error, `4` ffmpeg missing for HLS, `5` one or more downloads failed. Preserving these codes matters for scripting against the CLI.
- A `timestamp <= 0` (no broadcast date) is treated specially throughout: `naming.render` renders `{year}`/`{date}` as the literal string `"unknown"`, and `episodes.assign` places such undated, unparsed entries into season `0` — both deliberately avoiding the misleading Unix-epoch year 1970 that a naive `datetime.fromtimestamp(0)` would produce.
- `download`'s resume logic can silently restart from byte 0: if a `.part` file exists but a subsequent `206` response's declared total disagrees with the caller-supplied `expected_size`, the partial is discarded and refetched from scratch on a second attempt (at most one retry). Malformed (`content-length: garbage`) headers are ignored rather than raised.
- `download_hls` never leaves an orphaned ffmpeg process: stderr is streamed to a temp file (not a `PIPE`, which can deadlock the child if unread), and both the stall watchdog (`stall_timeout`, default 300s, based on `.part` size not changing) and the `finally` block kill any still-running process.
- `pretty_exceptions_show_locals=False` is set on the Typer app deliberately, since local variables in a traceback could include API responses or file paths a user wouldn't want dumped to a shared terminal/log.
- `_make_progress` in `cli.py` uses two separate Rich `Progress` instances (files-overall vs. bytes-per-file) stacked in one `Group`/`Live` because a single `Progress` applies one column set to every task, which previously produced nonsensical output like "10/10 bytes".

Created and maintained by Nori.
