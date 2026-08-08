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