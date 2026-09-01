-- Cross-meeting Person identity (the Phase-0 foundation).
-- A person is anchored on calendar-attendee email (person_emails) and linked
-- to meetings via meeting_attendees; speakers.person_id bridges a diarized
-- per-meeting speaker to the cross-meeting identity. Voiceprints are
-- deliberately absent (deferred — biometric consent).

CREATE TABLE people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT,
    notes TEXT NOT NULL DEFAULT '',      -- human-authored, survives everything
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One email belongs to exactly one person: the dedupe/upsert anchor.
-- Emails are stored lowercased (enforced in the repository).
CREATE TABLE person_emails (
    email TEXT PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    is_primary INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_person_emails_person ON person_emails(person_id);

-- Meeting-level attribution: who was in the room (calendar roster, or a
-- manual link). Scales to any meeting size — no per-utterance claim.
CREATE TABLE meeting_attendees (
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'calendar',   -- calendar | manual
    PRIMARY KEY (meeting_id, person_id)
);

CREATE INDEX idx_meeting_attendees_person ON meeting_attendees(person_id);

-- Bridge a per-meeting diarized speaker to a cross-meeting person.
ALTER TABLE speakers ADD COLUMN person_id INTEGER REFERENCES people(id) ON DELETE SET NULL;
