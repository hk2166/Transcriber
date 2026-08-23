# Show HN draft

**Title:**
Show HN: Confab – meeting transcription and AI notes that never leave your Mac

**Post:**

I got uncomfortable with how many meeting-notes tools upload everything you say
to someone else's servers (or worse, join your calls as a visible bot), so I
built Confab: a macOS app where the entire pipeline — recording, transcription,
summarization, search — runs locally.

What it does:

- Live transcription (~2 s behind your voice) using faster-whisper on-device
- Post-meeting AI notes via a local LLM through Ollama: summary, key points,
  action items, decisions, open questions, and an auto-generated title
- Semantic search across every meeting (ONNX MiniLM embeddings, local index)
- "Chat with this meeting" — RAG over the transcript, answers with citations
- Export to Markdown/PDF/Word/JSON
- Captures both mic and system audio (system side via BlackHole), so remote
  calls get both sides without any bot joining

Architecture, for the curious: Tauri 2 shell (React UI) with a Python FastAPI
sidecar bundled by PyInstaller, talking over localhost on a random port. The
live path is capture → Silero VAD → Whisper → SQLite. The heavier stuff
(summaries, embedding/indexing) runs as background jobs after the meeting ends.
Keeping the sidecar torch-free (CTranslate2 for Whisper, ONNX for VAD and
embeddings) got the whole app down to a 115 MB download.

It's free, and the privacy claim is falsifiable: unplug your network
mid-meeting and everything keeps working.

Known gaps: speaker labels are dev-complete but cut from v1 to stay lean
(coming in v1.1), and the first-run model download (~460 MB) has no progress
bar yet. Windows is next.

Download + source: https://github.com/hk2166/Transcriber
