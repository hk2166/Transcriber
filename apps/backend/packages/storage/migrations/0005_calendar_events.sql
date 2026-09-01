-- Calendar-event cache: the identity anchor's raw material.
-- One row per Google event we fetched; meeting_id links the event a recording
-- was time-matched to (the source of that meeting's attendee links).

CREATE TABLE calendar_events (
    event_id TEXT PRIMARY KEY,
    title TEXT,
    start_iso TEXT NOT NULL,
    end_iso TEXT NOT NULL,
    attendees_json TEXT NOT NULL DEFAULT '[]',
    meeting_id INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_calendar_events_meeting ON calendar_events(meeting_id);
