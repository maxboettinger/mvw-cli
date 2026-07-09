# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Coverage gate in CI (`pytest-cov`, ≥ 90%) and a single `all-green` status
  check that branch protection on `main` requires.
- Dependabot keeps GitHub Actions SHA pins and Python dependencies updated.

## [0.3.0] - 2026-07-09

### Added

- `mvw --version` / `-V` prints the installed version.
- CI workflow: lint (ruff), type check (mypy), and a test matrix across
  Python 3.11–3.13 on Linux, macOS, and Windows.
- `CONTRIBUTING.md` with development and release documentation.
- The package now ships a `py.typed` marker for downstream type checkers.
- GitHub Releases are created automatically on each published tag.

### Changed

- Python 3.11 and 3.12 are now supported (previously 3.13+ only).
- Subtitles are saved as Plex-friendly sidecars (`<video>.de.<ext>`, extension
  taken from the subtitle URL) instead of `<video>.xml`.
- Entries without a broadcast date land in `Season 00` with year `unknown`
  instead of the misleading epoch year 1970.
- API requests retry server errors (5xx) with exponential backoff and report
  a clear error for non-JSON responses.
- The HTTP `User-Agent` now tracks the installed package version.
- `--sort`, `--order`, and `--resolution` values are validated up front.

### Fixed

- Invalid `--template`, `--exclude` regexes, corrupt `config.toml` files,
  unknown config keys, and uncoercible config values now produce friendly
  error messages and exit code 2 instead of Python tracebacks.
- Tracebacks no longer dump local variables (which could include config
  values and URLs).
- A malformed `Content-Length` header no longer crashes a download.
- Two entries resolving to the same target file are detected; the duplicate
  is skipped with a warning instead of silently miscounted.
- A stalled ffmpeg HLS transfer is killed after a timeout (default 300 s)
  instead of hanging the run indefinitely.

## [0.2.0] - 2026-06-27

### Added

- Verified downloads: existing files are checked against the remote size
  (HTTP HEAD with ranged-GET fallback); valid files are skipped, corrupt
  files are redownloaded, and `--force` redownloads unconditionally.
- Downloads stage to a `.part` file (including HLS) and are promoted only
  after the size check passes, so interrupted transfers never leave a
  corrupt final file.
- A run summary line: `Done: N downloaded, N skipped, N redownloaded, N failed`.

### Fixed

- Subtitle download failures no longer fail the video download.

## [0.1.2] - 2026-06-27

### Fixed

- Overall progress bar counts files instead of bytes; HLS downloads report
  live progress.

## [0.1.1] - 2026-06-27

Initial public release on PyPI: `mvw search`, `mvw download` (Plex-friendly
season downloads, dedup, exclude filters, HLS via ffmpeg), `mvw info`, and
`mvw config`.

[Unreleased]: https://github.com/maxboettinger/mvw-cli/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/maxboettinger/mvw-cli/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/maxboettinger/mvw-cli/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/maxboettinger/mvw-cli/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/maxboettinger/mvw-cli/releases/tag/v0.1.1
