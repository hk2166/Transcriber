# Diarization

Speaker diarization for MeetingMind, built on `pyannote/speaker-diarization-3.1`.

## Model licensing & distribution decision (2026-08-08)

The pipeline depends on:

| Model | License | HF-gated? |
|---|---|---|
| pyannote/speaker-diarization-3.1 (pipeline config) | MIT | Yes |
| pyannote/segmentation-3.0 | MIT | Yes |
| pyannote/wespeaker-voxceleb-resnet34-LM (embedding) | CC-BY-4.0 | No |

Both licenses permit redistribution (CC-BY-4.0 requires attribution). The HF gate is an
access mechanism on Hugging Face's hosting, not a license term — once obtained, the
weights may legally be shipped.

**Decision: first-run download from our own GitHub release assets** — not bundled in the
DMG, not fetched from Hugging Face:

- End users never need an HF account or token.
- The onboarding wizard (Day 13) already has a model-download step for Whisper; these
  weights (~6 MB segmentation + ~26 MB embedding) ride along at zero extra UX cost.
- We control availability if HF gating rules ever change.
- The app's acknowledgements screen credits both models (CC-BY-4.0 attribution for the
  wespeaker embedding; MIT notices for pyannote).

Implementation note (Day 8): load the pipeline from a local config pointing at the
downloaded weights (`Pipeline.from_pretrained` on a local path). No `HF_TOKEN` anywhere
in the shipped app.

## pyannote 4.x notes (verified 2026-08-17)

- **Loads offline from cache** in ~4 s with `HF_HUB_OFFLINE=1` — no HF token at runtime.
- ⚠️ **Do NOT pass a file path** to the pipeline. pyannote 4.x decodes audio via
  `torchcodec`, which needs ffmpeg 4.x dylibs (`libavutil.56`) that aren't reliably
  present → crash. Instead **pass a waveform tensor**: `pipeline({"waveform":
  torch.from_numpy(audio).reshape(1, -1), "sample_rate": sr})`. We already have the WAV,
  so we load it with `soundfile` and skip torchcodec entirely.
- Output API changed: `pipeline(...)` returns a `DiarizeOutput`; the classic
  `Annotation` is at `out.speaker_diarization` (use `.itertracks(yield_label=True)`).
- Speed: **RTF ≈ 0.31** on Apple Silicon CPU/MPS (30-min meeting → ~9 min). Post-meeting
  only — never on the live path.
- torch/pyannote are **excluded from the Phase-1 packaged binary** (Day 7). Diarization's
  packaging is its own Day-16 problem (separate process or ONNX). Cut-line #3 still stands.