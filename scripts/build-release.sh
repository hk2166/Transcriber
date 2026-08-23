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
# tauri-bundler reads APPLE_SIGNING_IDENTITY from the environment on its own.
( cd "$DESKTOP" && npm run tauri build )

BUNDLE_DIR="$DESKTOP/src-tauri/target/release/bundle"
DMG="$(ls "$BUNDLE_DIR"/dmg/*.dmg | head -1)"
APP="$BUNDLE_DIR/macos/Confab.app"

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
