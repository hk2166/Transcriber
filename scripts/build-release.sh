#!/usr/bin/env bash
# Build the Confab macOS release: backend binary → Tauri app → DMG.
#
#   Unsigned (local testing):  ./scripts/build-release.sh
#   Signed:                    APPLE_SIGNING_IDENTITY="Developer ID Application: NAME (TEAMID)" ./scripts/build-release.sh
#   Signed + notarized:        …plus NOTARY_PROFILE=confab
#   Reuse existing backend:    SKIP_BACKEND=1 ./scripts/build-release.sh
#
# Signing prereqs: Apple Developer Program membership, a "Developer ID
# Application" certificate in the login keychain, and for notarization a
# stored notarytool profile:
#   xcrun notarytool store-credentials confab --apple-id you@example.com --team-id TEAMID
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/apps/backend"
DESKTOP="$ROOT/apps/desktop"
ENTITLEMENTS="$DESKTOP/src-tauri/Entitlements.plist"
IDENTITY="${APPLE_SIGNING_IDENTITY:-}"

if [ "${SKIP_BACKEND:-}" = "1" ] && [ -d "$BACKEND/dist/confab-backend" ]; then
  echo "==> 1/4 Reusing existing backend binary (SKIP_BACKEND=1)"
else
  echo "==> 1/4 Backend binary (PyInstaller)"
  ( cd "$BACKEND" && rm -rf build dist && uv run pyinstaller --noconfirm confab-backend.spec )
fi

if [ -n "$IDENTITY" ]; then
  echo "==> 2/4 Deep-signing backend Mach-O files"
  # Notarization requires every nested Mach-O to carry a hardened-runtime
  # signature; the bundler won't re-sign resource files for us.
  find "$BACKEND/dist/confab-backend" -type f | while read -r f; do
    case "$(file -b "$f")" in
      Mach-O*) codesign --force --options runtime --timestamp \
                 --entitlements "$ENTITLEMENTS" -s "$IDENTITY" "$f" ;;
    esac
  done
else
  echo "==> 2/4 Skipping backend signing (APPLE_SIGNING_IDENTITY not set)"
fi

echo "==> 3/4 Tauri build (app + DMG)"
# bundle_dmg.sh aborts if a prior/interrupted run left the DMG volume mounted.
hdiutil detach "/Volumes/Confab" -force >/dev/null 2>&1 || true
# tauri-bundler reads APPLE_SIGNING_IDENTITY from the environment on its own.
# Its DMG step (bundle_dmg.sh) drives Finder via AppleScript and can fail when
# the build runs detached/headless — the .app still builds fine, and we fall
# back to a plain hdiutil DMG below.
( cd "$DESKTOP" && npm run tauri build ) || echo "   (bundler returned non-zero — checking outputs)"

BUNDLE_DIR="$DESKTOP/src-tauri/target/release/bundle"
APP="$BUNDLE_DIR/macos/Confab.app"
[ -d "$APP" ] || { echo "✗ Confab.app was not built — aborting." >&2; exit 1; }

DMG="$(ls "$BUNDLE_DIR"/dmg/*.dmg 2>/dev/null | head -1)"
if [ -z "${DMG:-}" ] || [ ! -f "$DMG" ]; then
  echo "   no DMG from bundle_dmg.sh — building one with hdiutil (no Finder needed)"
  hdiutil detach "/Volumes/Confab" -force >/dev/null 2>&1 || true
  STAGE="$(mktemp -d)/Confab"; mkdir -p "$STAGE"
  ditto "$APP" "$STAGE/Confab.app"   # ditto preserves the sidecar's dylib symlinks
  ln -s /Applications "$STAGE/Applications"
  DMG="$BUNDLE_DIR/dmg/Confab_0.1.0_aarch64.dmg"
  mkdir -p "$(dirname "$DMG")"; rm -f "$DMG"
  hdiutil create -volname "Confab" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
fi

if [ -n "${NOTARY_PROFILE:-}" ]; then
  echo "==> 4/4 Notarizing $(basename "$DMG")"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler staple "$APP" || echo "   (app staple failed — fine if you distribute the DMG)"
else
  echo "==> 4/4 Skipping notarization (NOTARY_PROFILE not set)"
fi

mkdir -p "$ROOT/release"
cp "$DMG" "$ROOT/release/"
echo ""
echo "Done → release/$(basename "$DMG")"
