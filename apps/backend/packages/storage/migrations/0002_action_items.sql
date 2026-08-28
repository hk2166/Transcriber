-- Cross-meeting action items with persisted done-state.
-- Rows are (re)generated from each meeting's summary; done survives
-- re-summarisation when the text is unchanged (see replace_action_items).

CREATE TABLE action_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_action_items_meeting ON action_items(meeting_id);

-- Backfill from existing summaries (action_items is a JSON array of strings;
-- je.key is the 0-based array index).
INSERT INTO action_items (meeting_id, text, position)
SELECT s.meeting_id, je.value, je.key
FROM summaries s, json_each(s.action_items) je
WHERE s.action_items IS NOT NULL AND json_valid(s.action_items);
