#!/bin/sh
# Create and push a release tag. The GitHub workflow publishes the artifacts.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

if [ ! -f VERSION ]; then
    echo "Brak pliku VERSION." >&2
    exit 1
fi
VERSION=$(cat VERSION | tr -d '[:space:]')
TAG="v$VERSION"

if [ -n "$(git status --porcelain)" ]; then
    echo "Drzewo robocze nie jest czyste. Zrób commit przed release." >&2
    exit 1
fi

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1; then
    echo "Tag $TAG już istnieje." >&2
    exit 1
fi

PYTHON=${PYTHON:-}
if [ -z "$PYTHON" ]; then
    if [ -x "$ROOT/venv/bin/python" ]; then
        PYTHON="$ROOT/venv/bin/python"
    else
        PYTHON=python3
    fi
fi
"$PYTHON" -m py_compile main.py core.py db.py amazon.py stores.py store_ui.py
"$PYTHON" -m unittest discover -s tests -v

git tag -a "$TAG" -m "Boostlayer $VERSION"
git push origin HEAD
git push origin "$TAG"
echo "Wypchnięto $TAG; workflow release opublikuje AppImage i .deb."
