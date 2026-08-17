-- Initial schema: meetings and their transcripts.
-- speakers + summaries are created now but populated later (Days 8–9).

CREATE TABLE meetings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    source      TEXT NOT NULL,                       -- mic | system | both
    status      TEXT NOT NULL DEFAULT 'recording',   -- recording | processing | ready
    wav_path    TEXT,
    started_at  TEXT NOT NULL,                        -- ISO 8601
    ended_at    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE speakers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,                        -- e.g. "Speaker 1"
    name        TEXT,                                 -- user-assigned override
    color       TEXT NOT NULL                         -- deterministic hex
);

CREATE TABLE transcript_segments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    speaker_id  INTEGER REFERENCES speakers(id) ON DELETE SET NULL,
    text        TEXT NOT NULL,
    start_ms    INTEGER NOT NULL,
    end_ms      INTEGER NOT NULL,
    language    TEXT,
    confidence  REAL
);

CREATE INDEX idx_segments_meeting ON transcript_segments(meeting_id, start_ms);

CREATE TABLE summaries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id     INTEGER NOT NULL UNIQUE REFERENCES meetings(id) ON DELETE CASCADE,
    summary        TEXT,
    key_points     TEXT,   -- JSON array
    action_items   TEXT,   -- JSON array
    decisions      TEXT,   -- JSON array
    open_questions TEXT,   -- JSON array
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
