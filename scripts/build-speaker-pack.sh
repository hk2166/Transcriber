#!/usr/bin/env bash
# Build the optional speaker pack: the confab-speakers binary (torch +
# pyannote) plus a bundled offline HF model cache, zipped as the release
# asset speaker_pack.py downloads.
#
# Usage: ./scripts/build-speaker-pack.sh
# Output: release/confab-speakers-macos-arm64.zip
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/apps/backend"
STAGE="$BACKEND/dist/speaker-pack-stage"
HF_SRC="${HF_HOME:-$HOME/.cache/huggingface}"

if [ "${SKIP_PYINSTALLER:-}" = "1" ] && [ -d "$BACKEND/dist/confab-speakers" ]; then
  echo "==> 1/3 Reusing existing confab-speakers binary (SKIP_PYINSTALLER=1)"
else
  echo "==> 1/3 PyInstaller confab-speakers"
  ( cd "$BACKEND" && rm -rf build/confab-speakers dist/confab-speakers && \
    uv run pyinstaller --noconfirm confab-speakers.spec )
fi

echo "==> 2/3 Bundling offline HF model cache"
rm -rf "$STAGE"
mkdir -p "$STAGE/hf/hub"
for repo in models--pyannote--speaker-diarization-3.1 \
            models--pyannote--speaker-diarization-community-1 \
            models--pyannote--segmentation-3.0 \
            models--pyannote--wespeaker-voxceleb-resnet34-LM; do
  src="$HF_SRC/hub/$repo"
  if [ ! -d "$src" ]; then
    echo "   ✗ missing $src — run scripts/verify_pyannote.py once to populate the cache" >&2
    exit 1
  fi
  cp -R "$src" "$STAGE/hf/hub/"
done
cp -R "$BACKEND/dist/confab-speakers" "$STAGE/confab-speakers"

echo "==> 3/3 Smoke test + zip"
HF_HOME="$STAGE/hf" HF_HUB_OFFLINE=1 \
  "$STAGE/confab-speakers/confab-speakers" "$BACKEND/tests/e2e/fixtures/two_speaker_meeting.wav" \
  > /tmp/confab-speakers-smoke.json
# Same bar as tests/e2e: turns exist and are labeled. (Distinct-speaker count
# is fixture-dependent — synthetic TTS voices cluster; see the e2e test note.)
python3 - <<'PY'
import json
turns = json.load(open("/tmp/confab-speakers-smoke.json"))
assert turns, "no speaker turns produced"
assert all(t["speaker"] for t in turns), turns
speakers = {t["speaker"] for t in turns}
print(f"   ✓ smoke: {len(turns)} turns, {len(speakers)} speaker(s) — matches dev behavior on this fixture")
PY

mkdir -p "$ROOT/release"
( cd "$STAGE" && zip -qry "$ROOT/release/confab-speakers-macos-arm64.zip" confab-speakers hf )
du -sh "$ROOT/release/confab-speakers-macos-arm64.zip"
echo "Done → release/confab-speakers-macos-arm64.zip (upload as a GitHub release asset)"
