# Contributing

Thanks for your interest in improving `mvw`!

## Development setup

The project uses [uv](https://github.com/astral-sh/uv) for everything:

```bash
git clone https://github.com/maxboettinger/mvw-cli.git
cd mvw-cli
uv sync                # creates the dev environment (Python ≥ 3.11)
uv run mvw --help      # run from the working tree
```

## Quality checks

All of these run in CI on every push and pull request; please run them locally
before opening a PR:

```bash
uv run pytest -q               # unit and mocked tests
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run mypy src                # type check
```

There is one opt-in test that hits the real MediathekViewWeb API:

```bash
uv run pytest -m live tests/test_live.py -v
```

## Guidelines

- Add or update tests for any behavior change; the suite is fast and mocked
  (httpx via respx), so there is no excuse. :)
- User-facing errors must be friendly panels with a documented exit code —
  never raw tracebacks. See the exit-code table in the README.
- Record notable changes in `CHANGELOG.md` under **Unreleased**.

## Releasing (maintainers)

Cutting a release is one command. It verifies the tree is clean and in sync,
runs the tests, bumps the version, commits, tags, and pushes — and the pushed
tag triggers the GitHub Actions workflow that publishes to PyPI via Trusted
Publishing and creates a GitHub Release.

```bash
scripts/release.sh            # patch bump (default): 0.1.0 → 0.1.1
scripts/release.sh minor      # 0.1.0 → 0.2.0
scripts/release.sh major      # 0.1.0 → 1.0.0
```

Before releasing, move the **Unreleased** section of `CHANGELOG.md` into a new
version heading.
