# Packaging spike — findings (Day 7)

Goal: prove the ship path exists — bundle the Python backend into a standalone
binary that runs the live-transcription demo with no terminal and no dev
servers, then drive it from Tauri as a sidecar.

## Headline finding: the live path is torch-free ✅

The Phase-1 live demo (capture → VAD → Whisper → storage) needs **none** of
torch, transformers, pyannote, or sentence-transformers:

- `faster-whisper` runs inference through **CTranslate2**, not torch. ctranslate2
  imports torch only in its `converters/` (model-conversion time), never at
  inference.
- Importing `faster_whisper` *incidentally* pulls transformers → torch into the
  process (because torch is installed in the dev venv), but transcription works
  with all four **blocked at import** — proven by a `sys.meta_path` blocker test.

So PyInstaller can `--exclude-module torch transformers pyannote
sentence_transformers scipy` and the binary still transcribes. That removes the
single biggest bloat source.

Dev-venv sizes (what we're excluding vs keeping):

| Package | Size | Bundled? |
| --- | --- | --- |
| torch | 402 MB | ❌ excluded |
| transformers | 49 MB | ❌ excluded |
| onnxruntime | 69 MB | ✅ (VAD) |
| ctranslate2 | 5 MB | ✅ (Whisper) |

torch/pyannote/sentence-transformers return in Phase 2 for **diarization
(Day 8)** and **search (Day 10)** — those features must run post-meeting and may
need their own packaging strategy (separate process, or ONNX replacements — see
Day 16 note about ONNX embeddings).

## Build

PyInstaller 6.22.2, `--onedir` (faster startup than `--onefile`, which unpacks
~200 MB to a temp dir on every launch):

```
uv run pyinstaller --noconfirm --onedir --name meetingmind-backend \
  --collect-all faster_whisper --collect-all ctranslate2 \
  --collect-all onnxruntime --collect-all av --collect-all sounddevice \
  --collect-submodules uvicorn \
  --add-data "packages/storage/migrations:packages/storage/migrations" \
  --exclude-module torch --exclude-module transformers \
  --exclude-module pyannote --exclude-module sentence_transformers \
  --exclude-module scipy --exclude-module matplotlib \
  server_main.py
```

Frozen entry point: `server_main.py` — binds a free localhost port, prints
`MEETINGMIND_PORT=<n>` on stdout (the Tauri host reads it), then runs uvicorn.

- **Bundle size:** **220 MB** (`dist/meetingmind-backend/`, torch excluded). For
  comparison, torch alone is 402 MB — excluding it roughly halved the bundle.
- **Cold startup:** ~2–3 s from launch to `MEETINGMIND_PORT=` + `/health` OK
  (onedir; onefile would add temp-unpack time on every launch).
- **Transcription in the frozen binary:** ✅ **works** — ran the frozen binary
  with no venv/uv, played speech into BlackHole, and it produced
  `Transcript [asr 1922ms]: The frozen binary is now transcribing…`. The full
  live pipeline (bundled sounddevice/PortAudio → onnxruntime VAD → CTranslate2
  Whisper → sqlite) runs standalone.

## Models are NOT bundled

Whisper (`small`, ~460 MB) and the segmentation/embedding weights are downloaded
to `~/.cache/huggingface` / the app data dir on first use — not in the binary.
The silero VAD ONNX ships *inside* faster-whisper's assets, so `--collect-all
faster_whisper` includes it, and the runtime `find_spec` path resolves inside
the bundle. First-run model download is the onboarding step (Day 13).

## What broke / had to be handled

- `--add-data` for `packages/storage/migrations` — `db.py` reads the `.sql`
  files from disk via `Path(__file__).parent`, so they must be bundled. Verified
  the frozen binary applies migrations (`Database ready …`).
- The runtime `find_spec("faster_whisper")` path for the silero VAD ONNX resolves
  correctly inside the frozen bundle (VAD works in the frozen binary).
- ⚠️ **Orphan process on kill.** Killing the launcher PID (`SIGTERM`) left a
  child running (PyInstaller bootloader child + uvicorn). The Tauri sidecar must
  kill the whole **process group** on quit — otherwise orphan backends pile up.
  Tauri's sidecar teardown should handle this; **verify in Activity Monitor on
  Day 16**. (`server_main.py` could also install a SIGTERM handler.)
- onedir vs onefile for the sidecar: Tauri `externalBin` wants a single
  target-triple-named binary. Options for Day 16: (a) `--onefile` (fits
  externalBin, slower cold start), or (b) keep `--onedir` and bundle the folder
  as a Tauri **resource**, spawning the inner binary via `Command` with the
  process-group kill above.

## Still to do (by Day 16)

- Tauri sidecar wiring: `externalBin`, Rust spawn + read the port handshake +
  kill on quit (verify no orphan process in Activity Monitor).
- Frontend reads the announced port instead of hardcoded 8765.
- `npm run tauri build` → unsigned `.app` runs the Day-5 demo.
- Then Day 16: sign + notarize + DMG; Phase-2 packaging for the torch features.
