#!/bin/bash
# Wraps dist/JARVIS.app (built by mark48-mac.spec) into a distributable
# drag-to-Applications .dmg. Run after `pyinstaller mark48-mac.spec`.
set -euo pipefail

cd "$(dirname "$0")/.."

APP="dist/JARVIS.app"
OUT_DIR="installer_output"
DMG_NAME="JARVIS-Setup.dmg"
STAGING="$(mktemp -d)"

if [ ! -d "$APP" ]; then
    echo "error: $APP not found — run 'pyinstaller mark48-mac.spec' first" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/$DMG_NAME"

cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

hdiutil create -volname "JARVIS" \
    -srcfolder "$STAGING" \
    -ov -format UDZO \
    "$OUT_DIR/$DMG_NAME"

rm -rf "$STAGING"
echo "Created $OUT_DIR/$DMG_NAME"
