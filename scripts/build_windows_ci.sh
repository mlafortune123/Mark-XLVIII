#!/bin/bash
# Triggers the Windows installer build via GitHub Actions (build-windows.yml
# workflow_dispatch). Does NOT build locally — PyInstaller's Windows output
# must come from an actual Windows machine/runner, so this always goes
# through CI. Requires `gh` authenticated against the repo.
#
# Usage: ./scripts/build_windows_ci.sh [version]
#   version defaults to the workflow's own default (48.0.0) if omitted.
set -euo pipefail

cd "$(dirname "$0")/.."

REPO="mlafortune123/Mark-XLVIII"
VERSION="${1:-}"

if [ -n "$VERSION" ]; then
    gh workflow run build-windows.yml -f version="$VERSION" -R "$REPO"
else
    gh workflow run build-windows.yml -R "$REPO"
fi

echo "Triggered build-windows.yml on $REPO. Watch it with:"
echo "  gh run watch -R $REPO"
echo "Download the finished installer with:"
echo "  gh run download <run-id> -D /tmp/jarvis-build -R $REPO"
