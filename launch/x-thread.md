# X / Twitter launch thread draft

**1/**
Every AI meeting-notes app has the same fine print: your conversations get
uploaded to their servers.

So I spent 20 days building one where they don't.

Confab — AI meeting notes that never leave your Mac. Free. 🧵

**2/**
What it does, all on-device:

⚡ Live transcription (~2 s behind your voice)
🧠 AI summary, action items & decisions after every meeting
🔎 Search every meeting by *meaning*
💬 Chat with any meeting, answers cited to the transcript
📄 Export MD / PDF / Word / JSON

**3/**
The privacy claim is falsifiable, not marketing:

Unplug your Wi-Fi mid-meeting. Recording, transcription, summaries, search —
everything keeps working. There is no server to reach.

**4/**
Under the hood (for the nerds):

- Tauri 2 + React shell, Python FastAPI sidecar
- faster-whisper (CTranslate2) for speech → text
- Silero VAD so silence never hits the transcriber
- Ollama for summaries & RAG chat
- ONNX MiniLM embeddings for search
- Torch-free bundle → 115 MB download

**5/**
Built in 20 days of daily shipping, from empty repo to notarized DMG.

macOS first (13.3+, Apple Silicon recommended). Windows is Phase 2.
Speaker labels in v1.1.

Download → [link]

RTs appreciated 🙏
