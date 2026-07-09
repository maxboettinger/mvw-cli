# Noridoc: or-cli (mvw-cli)

Path: @/

### Overview

- Repository for `mvw`, a Python CLI (distributed as `mvw-cli` on PyPI) that searches and downloads German public-broadcasting media from the MediathekViewWeb API, with Plex-friendly season downloads.
- The entire implementation lives under @/src/mvw — see its own docs at @/src/mvw/docs.md. This root document covers packaging, CI/release, and testing conventions that sit above that package.
- Single-package repo: no monorepo boundaries, no other services.

### How it fits into the larger codebase

- @/pyproject.toml is the single source of truth for the package version, dependencies, console-script entry points (`mvw`, `mvw-cli`), and tool configuration (`ruff`, `mypy`, `pytest`). A release is only valid if the git tag matches this version — enforced by @/.github/workflows/release.yml.
- @/tests mirrors @/src/mvw module-for-module (one `test_*.py` per module) and is fully mocked: `respx` stands in for the MVW API and direct-download HTTP traffic, and POSIX shell scripts stand in for `ffmpeg`. Only one test is marked `live` (hits the real API) and is excluded by default via `pytest.ini_options.addopts` in @/pyproject.toml.
- @/.github/workflows/ci.yml runs on every push/PR: lint (`ruff check`, `ruff format --check`), `mypy src`, then a test matrix across Python 3.11–3.13 on ubuntu/macos/windows. The fake-ffmpeg POSIX shell stubs are skipped on Windows (see the `posix_only` marker in @/tests/test_download.py); the HLS logic they exercise is otherwise platform-independent Python.
- @/scripts/release.sh is the only supported way to cut a release: it enforces a clean `main` branch synced with `origin`, runs the test suite, bumps the version via `uv version --bump`, commits, tags (`vX.Y.Z`), and pushes — which triggers @/.github/workflows/release.yml to build, publish to PyPI via Trusted Publishing (OIDC, no stored token), and create a GitHub Release.
- CI and release workflows pin third-party GitHub Actions by commit SHA (with the version as a trailing comment) rather than by tag, as a supply-chain hardening measure.

### Core Implementation

- N/A at this level — see @/src/mvw/docs.md for all business logic.

### Things to Know

- The package requires Python 3.11+ and ships `py.typed`, so downstream type checkers see this package as typed.
- `ruff` is configured to select `E, F, W, I, UP, B, SIM, RUF` and explicitly allows en/em dashes (`–`, `—`) as non-confusable, since they appear deliberately in user-facing strings and in the title-cleanup regexes in @/src/mvw/episodes.py.
- Dev tooling (`pytest`, `respx`, `ruff`, `mypy`) is declared as a `uv` dependency group in @/pyproject.toml, not a separate requirements file; CI and local dev both use `uv sync --locked` against @/uv.lock.
- @/CHANGELOG.md and @/CONTRIBUTING.md are maintained by hand; @/CONTRIBUTING.md asks contributors to record notable changes under an "Unreleased" heading in @/CHANGELOG.md before a release is cut.

Created and maintained by Nori.
