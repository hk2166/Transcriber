# Confab — manual QA

Rows to run on a real machine before a release. Automated coverage lives in the
`pytest` suite; these are the things only a human + real accounts can confirm.

## Notion sync (Phase 2)

Set up an internal connection at https://app.notion.com/developers/connections
(Internal connections → Create → Configuration tab: copy the installation
token; enable **Read content** and **Insert content**).

- [ ] Paste the token + an **unshared** page link → Test connection shows the
      share instructions ("Confab can't see that page…").
- [ ] Share the page (••• → Connections → + Add connection) → Test names the
      page: "Will file under <page> (page) as <bot>".
- [ ] Record or re-summarise a meeting → the Sync tab shows a **Notion** card
      with summary, key points, decisions, action items, open questions.
- [ ] Edit the content to include `*stars*` and `[brackets]` → Create page →
      they render **literally** on the Notion page (no italics, no broken link).
- [ ] Open in Notion ↗ opens the created page.
- [ ] Click Create page again → no duplicate (returns the same page).
- [ ] Repeat with a **database** link → the page appears as a row with the
      title in the title column.
- [ ] Revoke the token in the portal → Create page shows the token error;
      after pasting a fresh token, Retry succeeds.
- [ ] Turn the Notion toggle off in Settings → the next meeting proposes no
      Notion card.

## Apple automation (Phase 1) — packaged build only

- [ ] On the **signed** build: Sync tab → Add note → the macOS Automation
      prompt names **Confab** (not Terminal) → the note appears in Notes ›
      Confab. (TCC attributes the prompt to the responsible app bundle — the
      §5 risk in docs/INTEGRATIONS.md; only verifiable on a signed build.)
