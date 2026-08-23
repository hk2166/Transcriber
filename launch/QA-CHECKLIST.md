# Day 17 — Clean-machine QA checklist

Run on a **fresh macOS user account** (System Settings → Users & Groups → Add User),
or better, a Mac that has never seen the dev environment. The point is zero dev
tooling: no uv, no node, no HF cache, no Ollama, no BlackHole.

## Install

- [ ] Download the DMG from the release page (don't copy it over AirDrop — you want the quarantine bit set, like a real user)
- [ ] Open the DMG, drag Confab to Applications
- [ ] Launch. **Signed build:** must open with no Gatekeeper complaint. **Unsigned test build:** requires System Settings → Privacy & Security → "Open Anyway" — that's expected pre-notarization, and exactly why we notarize before launch.

## First run

- [ ] App window appears within ~5 s of launch (sidecar cold start)
- [ ] Click record → macOS microphone permission prompt appears, wording reads correctly, app is named "Confab"
- [ ] First recording triggers the Whisper model download (~460 MB). App stays responsive; transcript starts once the model is warm. *(Known v1 gap: no progress bar — the UI shows the warming state.)*
- [ ] Speak for 30 s → words appear live, < 3 s behind your voice
- [ ] Stop → meeting appears in the sidebar with a date title
- [ ] Settings panel: readiness rows show Ollama ✗ and BlackHole ✗ (neither installed) with guidance, not errors

## Degraded modes (nothing installed)

- [ ] Without Ollama: meeting page shows transcript; summary area explains Ollama is needed and links to install — no crash, no spinner-forever
- [ ] Without BlackHole: source selector defaults to mic; picking "system"/"both" explains BlackHole — no crash

## Full flow (after installing Ollama)

- [ ] `ollama pull llama3.2`, restart recording → stop → title + summary auto-appear
- [ ] Search finds a word you spoke; clicking the result opens the meeting
- [ ] Chat tab answers a question about the meeting with citations
- [ ] Export all four formats; files land in ~/Downloads and open in Preview/Word

## Robustness

- [ ] Quit the app mid-recording → relaunch → meeting recovered, no corrupt DB
- [ ] Activity Monitor after quit: **no `confab-backend` process left** (the process-group kill)
- [ ] Record a 30+ min meeting → memory stable, UI responsive
- [ ] Delete a meeting → gone from sidebar and from search results
- [ ] Settings → delete all data → app returns to first-run state

## Fit & finish

- [ ] App icon renders crisply in Dock, Cmd-Tab, and the DMG window
- [ ] Window title says Confab; About panel shows 0.1.0
- [ ] `~/Library/Application Support/Confab/` is where data lives; `~/Library/Logs/Confab/backend.log` exists and is readable

Fix everything found, rebuild, re-notarize, and repeat until this list is boring.
