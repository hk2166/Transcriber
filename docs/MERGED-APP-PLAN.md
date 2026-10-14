# Merged app — Confab + Sotto into one (plan)

**Goal:** one app that does both jobs — **dictation** (talk → clean text typed at
your cursor, voice-edit a selection) from Sotto, and **meeting capture &
recall** (record → transcribe → diarize → summarize → search → chat → file to
other apps) from Confab — with **Sotto's UI** as the shell. No feature dropped.

> Rights: proceeding on the basis that we own / are licensed for the Sotto code.
> This document is PR #0 (foundation). Every later PR in the roadmap builds on it.

---

## 1. Why this is a sequence of PRs, not one

The two apps don't share a runtime:

| | Confab | Sotto |
|---|---|---|
| Shell | Tauri 2 + React | **Electron + React + Tailwind** |
| Dictation engine | — | **Swift** (hotkey, Accessibility paste, Apple SpeechAnalyzer, warm Gemma via llama.cpp) |
| Meeting engine | **Python FastAPI sidecar** (faster-whisper/Parakeet, pyannote, Ollama/cloud, SQLite, ONNX search, integrations) | Notes feature (subset) |

A single mega-PR merging two shells + three backends would be unreviewable and
unmergeable. Instead: a foundation PR, then one PR per feature domain, each
green on its own.

## 2. Architecture decision

**Shell = Sotto's Electron app** (keeps Sotto's UI, as asked). The shell owns
the window, HUD/pill, tray, settings, and never touches audio.

**Two engines behind the shell:**

- **Dictation engine (native, macOS) — Swift**, from Sotto (`Tools/SottoEngine`
  + `Packages/SottoKit`/`SottoCore`). Owns the global hotkey, microphone for
  dictation, Apple SpeechAnalyzer, rule-based + LLM cleanup, Command Mode, and
  pasting at the cursor. Talks to the shell over Sotto's stdio line protocol.
- **Meeting engine — Python FastAPI sidecar**, from Confab (`apps/backend`).
  Owns meeting recording (mic + system via BlackHole), Whisper/Parakeet,
  pyannote diarization, summaries (Ollama + cloud + hosted tier), SQLite,
  ONNX semantic search, RAG chat, and the integrations. Talks to the shell over
  localhost HTTP, exactly as it does today.

```
            ┌───────────────────────── Electron shell (Sotto UI) ─────────────────────────┐
            │  HUD pill · tray · settings · Notes · Home · Styles · meeting views          │
            └───────▲───────────────────────────────────────────────────▲──────────────────┘
          stdio line proto                                        localhost HTTP
                    │                                                     │
        ┌───────────┴───────────┐                         ┌───────────────┴───────────────┐
        │ Swift dictation engine │                         │ Python meeting sidecar (Confab)│
        │ hotkey · OS speech ·   │                         │ capture · ASR · diarize ·      │
        │ cleanup · Command Mode │                         │ summarize · search · chat ·    │
        │ paste at cursor        │                         │ integrations · gateway         │
        └────────────────────────┘                         └────────────────────────────────┘
```

**Why not one backend:** rewriting Confab's Python meeting pipeline in Swift (or
Sotto's native dictation in Python) is months of work and throws away two
proven, tested codebases. Running both engines behind one shell keeps every
feature working from day one; a later PR can consolidate if we choose.

**Data:** one SQLite store. The Python side already owns `meetings`, `summaries`,
`segments`, `people`, `sync_proposals`. Sotto's dictation history / snippets /
dictionary / styles become new tables in the same DB (or a sibling store the
shell owns). Reconciled in the "unified store" PR.

**Cost of the decision:** a 3-process app (Electron + Swift + Python) → a bigger
bundle and more packaging work (Electron-builder + a Swift binary + the
PyInstaller sidecar). Accepted; addressed in the packaging PR.

## 3. Feature inventory — nothing skipped

### From Sotto (dictation side)
- [ ] Dictate in any app (tap/hold hotkey → type at cursor), HUD pill
- [ ] Command Mode (voice-edit a selection: shorten, translate, fix grammar)
- [ ] Styles: Clean / Professional / Casual / Concise / Technical / Grammar + custom + **per-app** styles
- [ ] Dictionary (names/jargon) and Snippets (spoken cue → saved text)
- [ ] Home (dictation history + search), Insights, Scratchpad
- [ ] Context awareness (pre-cursor text + window title, guarded; password-field safe; "never read in")
- [ ] Learn-from-corrections
- [ ] Apple SpeechAnalyzer path (instant STT, no model download) + rule-based fallback
- [ ] Hindi / Hinglish model option
- [ ] Menu-bar quick controls

### From Confab (meeting side)
- [ ] Live transcription (faster-whisper + Parakeet), pause/resume, post-meeting refine
- [ ] pyannote diarization (who said what) + speaker→person linking
- [ ] LLM summaries (Ollama + 9 cloud providers + hosted-tier gateway), auto titles
- [ ] Playback-synced transcript + transcript editing
- [ ] Action-item hub; semantic search across all meetings; RAG chat with citations
- [ ] People / cross-meeting identity + Google Calendar attendee linking + pre-call prep
- [ ] Integrations (Apple Reminders/Calendar/Notes, Notion, Google front door) behind propose→approve→apply
- [ ] Audio/video file import → transcript
- [ ] System + mic capture (BlackHole), call detection (Zoom/Webex auto-record)
- [ ] Export (Markdown / PDF / Word / JSON)
- [ ] Hosted-tier metering gateway + admin dashboard

### Overlap to reconcile (do once, not twice)
- Notes (Sotto) vs Meetings (Confab): converge on Confab's richer meeting
  pipeline; Sotto's Notes UI becomes a view onto it.
- Summaries: both have them → Confab's multi-provider summarizer wins.
- History/search: Sotto's dictation history + Confab's meeting search → one search.

## 4. Phased PR roadmap

| PR | Title | Contents | Gate |
|---|---|---|---|
| **0** | Merge plan (this) | Architecture, inventory, roadmap | Reviewed |
| 1 | Shell foundation | Sotto Electron shell imported; monorepo layout; root dev launcher runs shell + both engines | app boots, both engines handshake |
| 2 | Dictation core | Swift engine (hotkey, OS speech, cleanup, paste), HUD pill | dictate into any app |
| 3 | Meeting sidecar wired | Confab Python backend behind the Electron shell; Notes/Meetings view | record → transcript |
| 4 | Meeting intelligence | diarization, summaries, search, RAG chat | full meeting flow |
| 5 | Dictation extras | Command Mode, styles (+per-app), dictionary, snippets, context, insights | all Sotto features |
| 6 | Integrations & I/O | Apple/Notion/Google, export, file import | propose→apply works |
| 7 | Unified store + settings | one DB, one settings surface, migrations | data reconciled |
| 8 | Packaging & signing | Electron-builder + Swift binary + PyInstaller sidecar into one .app; Developer ID + notarization | installable signed build |

Each PR: builds, typechecks, tests green, independently reviewable.

## 5. Open questions (for the reviewer)
1. **Home repo:** this PR is on a branch in `hk2166/Transcriber`. Fresh app in a
   new repo instead? (If so, say which and I'll re-target.)
2. **"PRs for both":** a single fresh app is one PR stream. Confirm it lands here
   (Confab repo), vs. mirrored changes into the Sotto repo too.
3. **Consolidation:** keep the 3-process architecture, or schedule a later PR to
   fold the meeting pipeline into the native engine (drops Python, much larger)?

## 6. Risks
- **Bundle size / startup:** three runtimes. Mitigate: lazy-start the meeting
  sidecar (only when a meeting/Notes view opens); dictation stays instant.
- **Signing:** both apps are unsigned today; the merged app needs one Developer
  ID identity + notarization for the whole bundle (PR 8). Still blocked on Apple
  enrollment, same as Confab.
- **Platform:** Sotto targets macOS 26+ (Apple SpeechAnalyzer); Confab targets
  13.3+. Merged macOS floor = 26 for the native-speech path, with Whisper as the
  fallback on older macOS. Windows/Linux = later (Sotto's node engine + Confab
  has no Windows path yet).
