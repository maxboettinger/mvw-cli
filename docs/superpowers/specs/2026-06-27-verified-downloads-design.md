# Verified downloads with skip-existing — design

Date: 2026-06-27
Status: approved

## Problem

`mvw download` currently has no awareness of existing files and no integrity
verification:

- `_run_downloads` (`cli.py`) never checks whether the destination exists; it
  always downloads.
- `download()` ends with `part.replace(dest)`, unconditionally overwriting any
  existing file; `download_hls()` runs `ffmpeg -y`, also overwriting.
- `content-length` is read only to drive the progress bar; bytes written are
  never compared to any expected size, so a truncated stream is promoted to the
  final filename and reported as success.
- Resume blindly appends to any leftover `.part` via HTTP `Range` with no
  guard, so a changed remote file corrupts the result.
- `MediathekResult.size` (the API's exact expected byte count) is unused.

Result: every run re-downloads and overwrites everything, and corrupt/truncated
downloads can be silently presented as complete.

## Goals

- Skip files that already exist and are valid, with a clear status message.
- Detect corrupt/incomplete existing files (size mismatch / zero-byte) and
  redownload them, with a clear status message.
- Verify freshly downloaded files before promoting them to the final filename.
- Make resume safe against a changed remote.
- Report per-file status and an end-of-run summary.
- Provide `--force` to bypass skipping and redownload everything.

## Integrity model

The MVW API provides an exact expected byte `size` per entry but **no hash or
checksum**. Therefore integrity is verified by **byte size**, not content hash.

- HTTP downloads: expected size = API `size` when `> 0`, else the HTTP
  `Content-Length`. Tolerance is `0` (exact).
- HLS downloads (`.m3u8`): the output is a remuxed container with no reliable
  expected size, so validity = "exists and non-empty" only.

## Components

### 1. `verify_size` (`download.py`)

Single source of truth for "is this file valid?":

```python
def verify_size(path: Path, expected: int, *, tolerance: int = 0) -> bool
```

- `expected > 0`: valid iff `path` exists and `abs(size - expected) <= tolerance`.
- `expected <= 0`: valid iff `path` exists and size `> 0` (HLS / unknown-size).

### 2. Pre-download skip check (`cli.py::_run_downloads`)

The plan tuple is extended to carry the expected size:
`(dest, url, tier, sub_url, expected_size)`, where `expected_size` is
`ep.result.size`. For each item, unless `--force` is set:

- valid existing file → status **already exists, skipped**; counted as skipped;
  advance overall bar; no network request.
- exists but invalid → status **corrupted (size mismatch), redownloading**;
  counted as redownloaded; delete the bad file, then download.
- missing → download; counted as downloaded.

`--force` bypasses the check and always downloads (counted as downloaded).

HLS items evaluate validity through the `expected <= 0` branch of `verify_size`.

### 3. Post-download verification (`download.py`)

`download()` gains `expected_size: int | None`:

- After the stream completes, compute the effective expected size
  (`expected_size` if given and `> 0`, else the HTTP `Content-Length` total).
- If an effective expected size exists and bytes written != expected: delete
  `.part` and raise `DownloadError("size mismatch: got X, expected Y")`.
- Only on success is `.part` promoted via `part.replace(dest)`, so an
  interrupted/failed run never leaves a corrupt **final** file.

Resume guard: resume from an existing `.part` only if the server returns `206`
**and** the computed total equals the expected size. Otherwise discard `.part`
and restart from scratch (`wb`). On `200` the existing reset-to-`wb` behavior
applies.

`download_hls()` is unchanged: validity = ffmpeg exit code `0` + non-empty
output file.

### 4. Reporting (`cli.py`)

- Per-file status line printed via `console` (outside the Live progress group):
  - `✓ <name> — already exists, skipped`
  - `⚠ <name> — corrupted (size mismatch), redownloading`
  - `↓ <name> — downloaded`
  - `✗ <name> — failed: <reason>`
- End-of-run summary: `Done: N downloaded, N skipped, N redownloaded, N failed`.
- Exit codes preserved: ffmpeg missing → 4; any failure → 5; otherwise 0.
  Skips and redownloads alone are success.

## Testing

- `verify_size`: missing, zero-byte, exact match, off-by-one mismatch, and
  `expected <= 0` (HLS) cases.
- `download()`: size mismatch raises `DownloadError` and leaves no final file;
  correct size promotes to final; resume restarts on a non-206 response;
  resume restarts on a 206 whose total != expected; resume continues on a valid
  206.
- `_run_downloads`: skip path performs no download call; corrupt existing file
  is deleted and redownloaded; `--force` always downloads; summary tallies are
  correct — driven by a fake download function.

## Out of scope

- Content-hash verification (no checksum is available from the API).
- A pre-skip network probe of `Content-Length` (skip decisions are made from
  the API size already in hand).
