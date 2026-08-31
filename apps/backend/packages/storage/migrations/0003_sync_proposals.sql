-- Cross-app sync proposals (propose → approve → apply).
-- Rows are generated locally after each meeting; nothing is sent anywhere
-- until the user applies a specific proposal (docs/INTEGRATIONS.md).

CREATE TABLE sync_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                  -- reminder | event | note | page
    target TEXT NOT NULL,                -- integration id, e.g. "apple-reminders"
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',  -- JSON, kind-specific
    status TEXT NOT NULL DEFAULT 'proposed',
        -- proposed | applied | skipped | failed | stale
    external_ref TEXT,                   -- id/url returned by the target on apply
    error TEXT,                          -- last apply failure, user-visible
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at TEXT
);

CREATE INDEX idx_proposals_meeting ON sync_proposals(meeting_id, status);
