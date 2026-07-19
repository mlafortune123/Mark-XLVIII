#!/bin/bash
# Full macOS build: PyInstaller onedir .app, then wrap into a .dmg.
# Must be run on macOS (PyInstaller does not cross-compile) from an
# activated venv that has pyinstaller installed.
#
# Usage: ./scripts/build_mac.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

if ! command -v pyinstaller >/dev/null 2>&1; then
    echo "error: pyinstaller not found on PATH — activate the venv it's installed in first" >&2
    echo "  e.g. source .venv/bin/activate && ./scripts/build_mac.sh" >&2
    exit 1
fi

pyinstaller mark48-mac.spec
./scripts/build_dmg.sh
