#!/bin/zsh
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  print -u2 "error: the macOS DMG workflow requires Darwin"
  exit 2
fi

ROOT_DIR="$(cd "${0:A:h}/../.." && pwd)"
OUTPUT_DIR="${1:-$ROOT_DIR/dist/unsigned-macos}"
BUILD_DIR="${OUTPUT_DIR}/pyinstaller"
APP_NAME="Advanced AI Video Tools"
APP_PATH="${BUILD_DIR}/dist/${APP_NAME}.app"
DMG_PATH="${OUTPUT_DIR}/Advanced-AI-Video-Tools-2.0.0-unsigned.dmg"
PYINSTALLER_VERSION="6.16.0"

mkdir -p "$OUTPUT_DIR"
rm -rf "$BUILD_DIR"

cd "$ROOT_DIR"
uv run --with "pyinstaller==${PYINSTALLER_VERSION}" pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "com.pastrypersonal5.advancedaivideotools" \
  --distpath "${BUILD_DIR}/dist" \
  --workpath "${BUILD_DIR}/work" \
  --specpath "$BUILD_DIR" \
  src/advanced_ai_video_tools/gui_entry.py

if [[ ! -d "$APP_PATH" ]]; then
  print -u2 "error: PyInstaller did not produce ${APP_PATH}"
  exit 1
fi

PLIST="${APP_PATH}/Contents/Info.plist"
set_plist_string() {
  local key="$1"
  local value="$2"
  if /usr/libexec/PlistBuddy -c "Print :${key}" "$PLIST" >/dev/null 2>&1; then
    /usr/libexec/PlistBuddy -c "Set :${key} ${value}" "$PLIST"
  else
    /usr/libexec/PlistBuddy -c "Add :${key} string ${value}" "$PLIST"
  fi
}

set_plist_string "CFBundleDisplayName" "$APP_NAME"
set_plist_string "CFBundleName" "$APP_NAME"
set_plist_string "CFBundleShortVersionString" "2.0.0"
set_plist_string "CFBundleVersion" "2.0.0"
set_plist_string "LSMinimumSystemVersion" "26.5.2"
if /usr/libexec/PlistBuddy -c "Print :NSHighResolutionCapable" "$PLIST" >/dev/null 2>&1; then
  /usr/libexec/PlistBuddy -c "Set :NSHighResolutionCapable true" "$PLIST"
else
  /usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$PLIST"
fi

plutil -lint "$PLIST"
codesign --force --deep --sign - "$APP_PATH"
SIGNATURE_INFO="$(codesign -dv --verbose=4 "$APP_PATH" 2>&1)"
if [[ "$SIGNATURE_INFO" == *"Developer ID Application"* ]]; then
  print -u2 "error: development build unexpectedly has a Developer ID signature"
  exit 1
fi

rm -f "$DMG_PATH"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$APP_PATH" \
  -format UDZO \
  "$DMG_PATH"
hdiutil verify "$DMG_PATH"

print "Created unsigned development DMG: $DMG_PATH"
print "App bundle: $APP_PATH"
print "This artifact is not notarized and will trigger Gatekeeper warnings."
