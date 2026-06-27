#!/usr/bin/env bash
#
# Cut a release: bump the version, commit, tag, and push.
# Pushing the tag triggers .github/workflows/release.yml, which publishes to PyPI.
#
# Usage:
#   scripts/release.sh [patch|minor|major]   # default: patch
#
set -euo pipefail

LEVEL="${1:-patch}"
case "$LEVEL" in
  patch | minor | major) ;;
  *)
    echo "error: bump level must be patch, minor, or major (got '$LEVEL')" >&2
    exit 2
    ;;
esac

cd "$(git rev-parse --show-toplevel)"

# --- Safety checks -----------------------------------------------------------
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
  echo "error: releases must be cut from 'main' (on '$BRANCH')" >&2
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "error: working tree is dirty — commit or stash first" >&2
  exit 1
fi

git fetch --quiet origin main
if [ "$(git rev-parse @)" != "$(git rev-parse '@{u}')" ]; then
  echo "error: local 'main' is out of sync with origin/main — pull/push first" >&2
  exit 1
fi

# --- Test before tagging (the tag is immutable on PyPI) ----------------------
echo "==> Running tests"
uv run pytest -q

# --- Bump, commit, tag, push -------------------------------------------------
echo "==> Bumping $LEVEL version"
uv version --bump "$LEVEL"
VERSION="$(uv version --short)"
TAG="v$VERSION"

if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "error: tag $TAG already exists" >&2
  exit 1
fi

echo "==> Committing and tagging $TAG"
git add pyproject.toml uv.lock
git commit -m "release $VERSION"
git tag -a "$TAG" -m "Release $VERSION"

echo "==> Pushing main and tag $TAG"
git push --follow-tags origin main

echo "🚀 Released $TAG — GitHub Actions is now publishing to PyPI."
echo "   Watch: https://github.com/maxboettinger/mvw-cli/actions"
