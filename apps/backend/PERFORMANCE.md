# Performance notes (Day 15)

All measured on this Apple-Silicon Mac, CPU-only, models warm unless noted.

## Latency — spoken word → text on screen

Target: **< 3 s**. Measured end-to-end ≈ **1.7 s** (warm):

| Stage | Time | Notes |
| --- | --- | --- |
| VAD (Silero ONNX) | <1 ms / 64 ms block | negligible |
| Segmenter silence wait | 700 ms | fixed `min_silence_ms` before a segment closes |
| Whisper `small` ASR | ~1 s / 5 s clip | RTF **0.23** warm (int8, CTranslate2) |
| WebSocket → render | <10 ms | — |

**First** transcript of a session pays a one-time model load (~3–6 s). Fix
parked from Day 4: **preload Whisper at app startup** so the first utterance
isn't slow. Model latencies for reference: base RTF 0.06 · small 0.23 ·
medium 0.68.

## Intelligence latencies

- Summary (llama3.2): title ~2.6 s, structured summary ~3.3 s — background, fine.
- RAG chat: first token ~2.5 s, then streams.
- Embedding (all-MiniLM ONNX): ~3 ms/sentence. Search: **3 ms warm**, <1 s cold.

## e2e regression test

`tests/e2e/test_full_pipeline.py` runs a 32 s two-speaker WAV through VAD →
Whisper → pyannote → embedder (+ Ollama when up) and asserts segments,
transcription content, populated/ranking index, latency (RTF < 1), and summary.
~35 s; excluded from the fast suite (`pytest tests/e2e` to run).

## Open items (honest status)

- **60-minute soak (memory flat?)** — NOT yet run. Architecturally memory should
  stay flat: the stream queue is bounded (256 blocks), speech buffers are
  released to the worker each segment, and the recorder streams to disk rather
  than buffering. Needs an actual long run to confirm no leaks (worker task
  refs, socket churn).
- **Large-transcript UI virtualization** — the transcript renders every segment
  (no windowing). Fine for typical meetings (<500 segments); a 1000-segment
  meeting would mount 1000 nodes and could jank on scroll. Recommendation if it
  bites: `react-window` on the segment list. Not done yet.
