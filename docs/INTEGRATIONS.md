# Integrations — design (propose → approve → apply)

*Status: Phase 1 (Apple Reminders/Calendar/Notes) SHIPPED — Aug 2026. Verified
end-to-end against real Apple apps. Phase 2 (Notion) and 3 (OAuth) remain
design-only. One deviation from this doc: no separate `approved` status —
clicking Apply IS the approval, so statuses are proposed | applied | skipped |
failed | stale.*

Connect Confab to the apps where meeting outcomes live — Apple Reminders,
Calendar, Notes, then Notion, later Google/Slack — **without breaking the
product's core promise**. Nothing leaves the Mac automatically: after each
meeting Confab *proposes* what to file where, and only items the user
explicitly approves are applied.

> **Positioning: "Private by default, connected by consent."**
> Understanding happens on-device. Publishing happens only per-item, after a
> human yes. This turns integrations from a privacy liability into a
> differentiator — the assistant that asks before it files.

---

## 1. Invariants (non-negotiable)

1. **No auto-send.** No external call with meeting content until the user
   approves that specific proposal. No "approve all future" setting in v1.
2. **Local processing.** Extraction (what to propose) runs through the user's
   configured summary LLM — local Ollama by default. If the user has selected
   a cloud LLM provider, they've already accepted that boundary for summaries;
   extraction rides the same choice, never a different one.
3. **Never block `ready`.** Proposal generation is a best-effort post-meeting
   step, wrapped like diarization/summaries — any failure logs and moves on.
4. **Editable before send.** Every proposal's title/body is editable in the
   review UI; what you approve is exactly what's sent.
5. **Idempotent apply.** An applied proposal stores its external reference and
   can never double-apply. Re-summarising marks old un-applied proposals
   `stale` instead of duplicating.

---

## 2. Architecture

```
meeting ends
  → postprocess_job (existing): diarize → summarize → index
  → NEW: integrations.propose(meeting)          [local, best-effort]
        extractor (LLM) ──→ calendar-event drafts (title/time/attendees)
        action_items     ──→ reminder drafts (one per item, owner in notes)
        summary          ──→ note/page draft (markdown)
        → rows in sync_proposals (status=proposed)
  → UI: meeting turns "ready" + proposal count
        → banner/toast: "3 suggestions for this meeting → Review"
        → Sync tab on the meeting: proposal cards
  → user edits / approves / skips per card (or "Approve all" per meeting)
  → POST apply → integration executes → status=applied + external ref
```

### Package layout

```
apps/backend/packages/integrations/
  __init__.py        # registry: INTEGRATIONS list + get_integration(id)
  base.py            # Proposal model + Integration protocol + errors
  extractor.py       # LLM-assisted drafts (calendar events; graceful no-LLM fallback)
  apple.py           # Reminders / Calendar / Notes via osascript (AppleScript)
  notion.py          # Phase 2: REST via httpx, token from settings.api_keys["notion"]
  test_*.py          # extractor with mocked LLM; apple with injected script runner
```

### The contract (`base.py`)

```python
@dataclass
class ProposalDraft:
    kind: str            # "reminder" | "event" | "note" | "page"
    target: str          # integration id: "apple-reminders" | "apple-calendar" | ...
    title: str
    body: str            # markdown-ish; rendered per-target on apply
    payload: dict        # kind-specific: {"due_iso": ...} / {"start_iso", "duration_min"}

class Integration(Protocol):
    id: str
    label: str
    def available(self) -> bool: ...          # app installed / token present
    def propose(self, ctx: MeetingContext) -> list[ProposalDraft]: ...
    def apply(self, proposal: Proposal) -> AppliedRef: ...   # raises IntegrationError
```

`MeetingContext` = meeting row + summary + action items + transcript text —
assembled once in `propose_all()`, passed to every integration.

### Extraction (`extractor.py`)

- Reuses the **existing multi-provider LLM client** (same one as summaries).
- One structured-output call: given summary + transcript tail, return
  `{"events": [{"title", "start_iso", "duration_min"}]}` — dates resolved
  relative to the meeting's `started_at` ("next Thursday 2pm" → ISO).
- **No-LLM fallback:** if the provider is unavailable, still propose
  action-items → reminders and summary → note (no LLM needed for either);
  only calendar extraction is skipped.

---

## 3. Storage — migration `0003_sync_proposals.sql`

```sql
CREATE TABLE sync_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,               -- reminder | event | note | page
    target TEXT NOT NULL,             -- integration id
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',  -- JSON, kind-specific
    status TEXT NOT NULL DEFAULT 'proposed',
        -- proposed | approved | applied | skipped | failed | stale
    external_ref TEXT,                -- id/url returned by the target on apply
    error TEXT,                       -- last apply failure, user-visible
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at TEXT
);
CREATE INDEX idx_proposals_meeting ON sync_proposals(meeting_id, status);
```

Repository functions follow the house conventions (conn first, keyword-only
payloads, commit per call): `insert_proposals`, `get_proposals(meeting_id)`,
`update_proposal(id, *, title, body, payload)`, `set_proposal_status`,
`mark_meeting_proposals_stale(meeting_id)`.

---

## 4. API

| Route | Purpose |
| --- | --- |
| `GET /integrations` | Registry for Settings: `[{id, label, available, enabled, needs_token, configured}]` |
| `GET /meetings/{id}/proposals` | Proposal cards for the Sync tab |
| `PATCH /proposals/{id}` | Edit `{title, body, payload}` and/or set `{status: approved\|skipped}` |
| `POST /proposals/{id}/apply` | Apply one (sets `applied` + `external_ref`, or `failed` + `error`) |
| `POST /meetings/{id}/proposals/apply` | Apply every `approved` proposal; per-item results |

Apply runs the integration in a worker thread (AppleScript/HTTP are blocking),
per item, so one failure never poisons the batch.

### Settings additions

```python
integrations_enabled: dict[str, bool] = {}    # {"apple-reminders": true, ...}
notion_parent: str = ""                       # page/database id or pasted URL (Phase 2)
# Notion token lives in the existing chmod-600 api_keys dict: api_keys["notion"]
```

---

## 5. Targets

### Phase 1 — Apple apps (local, no cloud, no OAuth)

Via `osascript` (AppleScript) from the sidecar — no new Python deps, works in
the frozen bundle:

- **Reminders** — one reminder per action item, into a "Confab" list
  (created if missing); due date when the extractor found one.
- **Calendar** — events from extracted follow-ups, into a "Confab" calendar
  (isolation = easy cleanup, no clobbering the user's main calendar).
- **Notes** — meeting summary as a note in a "Confab" folder (AppleScript
  Notes accepts basic HTML for body formatting).

`available()` = app bundle exists (all three ship with macOS → effectively
always true; the check future-proofs the pattern for third-party targets).

**Permissions (packaging):** first apply per target triggers the macOS
automation prompt ("Confab wants to control Reminders"). Requires:
- `Info.plist`: `NSAppleEventsUsageDescription` ("Confab files your approved
  meeting notes, reminders, and events into Apple apps.") + per-target strings
  (`NSRemindersFullAccessUsageDescription`, `NSCalendarsFullAccessUsageDescription`).
- `Entitlements.plist`: `com.apple.security.automation.apple-events`.
- TCC attributes the prompt to the responsible app bundle (Confab.app), since
  the sidecar is spawned from it — **must verify on the packaged build**, it's
  the riskiest assumption in this design. Denied permission surfaces as a
  clear per-card error with a "fix in System Settings" hint.

### Phase 2 — Notion (one pasted token, no OAuth)

- Internal-integration token pasted in Settings (stored in `api_keys["notion"]`,
  chmod-600 file, redacted in `GET /settings` — machinery already exists).
- User pastes a parent page/database URL; we extract the id.
- Apply = `POST /v1/pages` with the summary as blocks (markdown → Notion
  blocks, small local converter; httpx is already a dependency).

### Phase 3 — Google Calendar/Docs, Slack (OAuth — deferred)

Full OAuth2 desktop flow: loopback `http://127.0.0.1:<port>/callback`, browser
consent, token + refresh storage. Real, well-understood work — but heavy, and
it drags Google Cloud project setup into a local-first app. Build only on
demonstrated demand. (Design note: the loopback server can reuse the sidecar's
existing localhost HTTP server with a dedicated route.)

---

## 6. UI

### Sync tab (meeting view)

Third tab: `Transcript | Chat | Sync` (state type widens to
`"transcript" | "chat" | "sync"`). Cards grouped by target:

```
┌─ 📅 Calendar — Confab calendar ────────────────────────┐
│ Follow-up: design review        Thu Sep 3 · 2:00 PM    │
│ [title + time editable inline]                         │
│                                   [Skip]  [Add event]  │
└────────────────────────────────────────────────────────┘
┌─ ✅ Reminders — 3 action items ────────────────────────┐
│ ☐ Freeze the build by Wednesday          [Skip] [Add]  │
│ ...                                                    │
└────────────────────────────────────────────────────────┘
  [Approve & apply all]        applied ✓ shows external link/ref where available
```

States per card: proposed → (edit) → applied ✓ / skipped / failed (error text
+ Retry). Motion: cards use the existing spring vocabulary (`segmentIn`), an
applied card settles with a check.

### Post-meeting prompt ("Both" decision)

When postprocess finishes and a meeting has `proposed` rows, the existing
refresh cycle surfaces a **banner** on the meeting (and a toast if the user is
elsewhere in the app): *"3 suggestions ready — Review"* → opens the Sync tab.
Reuses the `detect-banner` visual pattern. No system notifications in v1.

### Settings

An **Integrations** section: toggle per target; Notion shows token field
(existing key-input pattern) + parent-page field + "Test connection".

---

## 7. Failure modes

| Failure | Behavior |
| --- | --- |
| LLM down at propose time | Reminders/note proposals still created; calendar extraction skipped (logged) |
| Automation permission denied | Card → `failed` with "Enable in System Settings → Privacy → Automation" |
| Target app missing / token invalid | Integration `available()=false` → never proposes; Settings shows why |
| Apply crashes mid-batch | Per-item isolation; each card shows its own result |
| Meeting re-summarised | Old un-applied proposals → `stale` (hidden); applied ones untouched |
| Duplicate apply click | `applied` status checked server-side; second apply is a no-op returning the ref |

## 8. Testing

- `extractor`: mocked LLM → event drafts; date resolution relative to
  `started_at`; no-LLM fallback path.
- `apple.py`: AppleScript strings built + escaped correctly (quoting is the
  classic injection bug — meeting titles contain quotes); `osascript` runner
  injected so tests never touch real apps.
- Repository + endpoint tests on in-memory DB (house pattern).
- Manual packaged-build check: TCC prompt attribution (the §5 risk).

## 9. Build order

1. **P1a** — migration + repository + `base.py` + `propose_all` hook +
   endpoints; proposals from summary/action-items only (no LLM yet).
2. **P1b** — Sync tab UI + banner/toast + Settings toggles.
3. **P1c** — `apple.py` apply + packaging strings/entitlement + TCC check.
4. **P1d** — `extractor.py` calendar events (LLM structured output).
5. **P2** — Notion. **P3** — Google/Slack on demand.

Each step lands runnable and tested; P1a–P1d is roughly a day of focused work.
