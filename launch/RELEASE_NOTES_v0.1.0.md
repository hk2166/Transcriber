# Confab v0.1.0 — first public release 🎉

Private, on-device AI meeting notes for macOS. Everything below runs entirely
on your Mac — no cloud, no bots, no account.

## Highlights

- **Live transcription** — speech on screen in ~2 s (faster-whisper, local)
- **AI summaries** — summary, key points, action items, decisions, and open
  questions after every meeting, plus auto-generated titles (local LLM via Ollama)
- **Semantic search** across all meetings — search by meaning, not keywords
- **Chat with a meeting** — grounded answers with transcript citations
- **Export** to Markdown, PDF, Word, JSON
- **Mic + system audio** capture (system audio via BlackHole)
- **Private by construction** — models run locally; audio and transcripts never
  leave your machine

## Requirements

- macOS 13.3+, Apple Silicon recommended
- Optional: [Ollama](https://ollama.com) for summaries/chat · [BlackHole 2ch](https://existential.audio/blackhole/) for system audio

## Install

Download `Confab_0.1.0_aarch64.dmg` below, open it, drag Confab to Applications.
On first recording, Confab downloads the Whisper speech model (~460 MB, one time).

## Known limitations (v1)

- Speaker labels (diarization) ship in v1.1 — the engine works, we kept v1 lean
- No download progress bar for the first-run model fetch (the UI shows a warming state)
- English-optimized default model; language auto-detect is built in, quality varies

## Feedback

Issues and ideas → [GitHub Issues](https://github.com/hk2166/Transcriber/issues)
