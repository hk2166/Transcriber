"""Typed CRUD over the meetings schema.

Plain functions taking a ``sqlite3.Connection`` — no ORM, no globals. Read
results come back as dataclasses; writes take primitives so this package
stays independent of the transcription package.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

__all__ = [
    "ActionItem",
    "Meeting",
    "Person",
    "Proposal",
    "Segment",
    "Speaker",
    "StoredSummary",
    "add_meeting_attendee",
    "create_meeting",
    "create_speakers",
    "delete_meeting",
    "end_meeting",
    "get_action_items",
    "get_meeting",
    "get_meeting_ids_for_person",
    "get_meetings",
    "get_people",
    "get_person",
    "get_proposal",
    "get_proposals",
    "get_segments",
    "get_segments_by_ids",
    "get_speakers",
    "get_summary",
    "insert_proposals",
    "insert_segment",
    "link_speaker_to_person",
    "mark_proposals_stale",
    "merge_people",
    "rename_speaker",
    "replace_action_items",
    "replace_segments",
    "save_summary",
    "set_action_item_done",
    "set_meeting_status",
    "set_meeting_title",
    "set_person_notes",
    "set_proposal_result",
    "set_proposal_status",
    "set_segment_speaker",
    "update_proposal",
    "update_segment_text",
    "upsert_person_by_email",
]

#: Deterministic per-speaker colours (Apple system palette), assigned by order.
SPEAKER_COLORS = [
    "#0A84FF",
    "#FF9F0A",
    "#30D158",
    "#FF375F",
    "#BF5AF2",
    "#64D2FF",
    "#FFD60A",
    "#5E5CE6",
]


@dataclass
class Meeting:
    id: int
    title: str
    source: str
    status: str
    wav_path: str | None
    started_at: str
    ended_at: str | None
    segment_count: int = 0


@dataclass
class Segment:
    id: int
    meeting_id: int
    text: str
    start_ms: int
    end_ms: int
    language: str | None
    confidence: float | None
    speaker_id: int | None


@dataclass
class Speaker:
    id: int
    meeting_id: int
    label: str  # "Speaker 1" (auto) — overridden by name
    name: str | None  # user-assigned
    color: str
    person_id: int | None = None  # cross-meeting identity bridge


@dataclass
class Person:
    """A cross-meeting identity, anchored on email (calendar attendees)."""

    id: int
    display_name: str | None
    primary_email: str | None
    notes: str
    meeting_count: int
    last_met: str | None  # started_at of the most recent linked meeting
    created_at: str


@dataclass
class StoredSummary:
    summary: str
    key_points: list[str]
    action_items: list[str]
    decisions: list[str]
    open_questions: list[str]


@dataclass
class ActionItem:
    id: int
    meeting_id: int
    meeting_title: str
    meeting_started_at: str
    text: str
    done: bool


@dataclass
class Proposal:
    """A cross-app sync suggestion; sent nowhere until the user applies it."""

    id: int
    meeting_id: int
    kind: str  # reminder | event | note | page
    target: str  # integration id
    title: str
    body: str
    payload: dict  # kind-specific (parsed JSON)
    status: str  # proposed | applied | skipped | failed | stale
    external_ref: str | None
    error: str | None
    created_at: str
    applied_at: str | None


def _title_for(started_at: datetime) -> str:
    """Human auto-title, e.g. ``Meeting — Aug 14, 9:30 AM`` (LLM titles: Day 9).

    Formatted without ``strftime`` ``%-`` flags so it also works on Windows.
    """
    hour = started_at.hour % 12 or 12
    meridiem = "AM" if started_at.hour < 12 else "PM"
    return (
        f"Meeting — {started_at.strftime('%b')} {started_at.day}, "
        f"{hour}:{started_at.minute:02d} {meridiem}"
    )


def create_meeting(
    conn: sqlite3.Connection,
    *,
    source: str,
    wav_path: str | None,
    started_at: datetime,
) -> int:
    """Insert a new meeting in ``recording`` status; return its id."""
    cursor = conn.execute(
        "INSERT INTO meetings (title, source, status, wav_path, started_at) "
        "VALUES (?, ?, 'recording', ?, ?)",
        (_title_for(started_at), source, wav_path, started_at.isoformat()),
    )
    conn.commit()
    return int(cursor.lastrowid)


def end_meeting(
    conn: sqlite3.Connection,
    meeting_id: int,
    *,
    ended_at: datetime,
    status: str = "ready",
) -> None:
    """Mark a meeting finished."""
    conn.execute(
        "UPDATE meetings SET ended_at = ?, status = ? WHERE id = ?",
        (ended_at.isoformat(), status, meeting_id),
    )
    conn.commit()


def insert_segment(
    conn: sqlite3.Connection,
    meeting_id: int,
    *,
    text: str,
    start_ms: int,
    end_ms: int,
    language: str | None,
    confidence: float | None,
    speaker_id: int | None = None,
) -> int:
    """Append a transcript segment; return its id."""
    cursor = conn.execute(
        "INSERT INTO transcript_segments "
        "(meeting_id, speaker_id, text, start_ms, end_ms, language, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (meeting_id, speaker_id, text, start_ms, end_ms, language, confidence),
    )
    conn.commit()
    return int(cursor.lastrowid)


def replace_segments(
    conn: sqlite3.Connection, meeting_id: int, segments: Sequence
) -> int:
    """Swap a meeting's transcript for a freshly re-transcribed one, atomically.

    Used by the post-meeting refine pass. Each item needs ``text``, ``start_ms``,
    ``end_ms``, ``language``, ``confidence`` (e.g. a
    :class:`~packages.transcription.TranscriptSegment`). The delete and inserts
    run in one transaction, so a failure never leaves the meeting empty. Speaker
    attributions are dropped — the new segments start unattributed and
    diarization re-runs over them. Returns the number of segments written.
    """
    with conn:  # BEGIN … COMMIT (or ROLLBACK on error)
        conn.execute(
            "DELETE FROM transcript_segments WHERE meeting_id = ?", (meeting_id,)
        )
        conn.executemany(
            "INSERT INTO transcript_segments "
            "(meeting_id, speaker_id, text, start_ms, end_ms, language, confidence) "
            "VALUES (?, NULL, ?, ?, ?, ?, ?)",
            [
                (meeting_id, s.text, s.start_ms, s.end_ms, s.language, s.confidence)
                for s in segments
            ],
        )
    return len(segments)


def get_meetings(conn: sqlite3.Connection) -> list[Meeting]:
    """All meetings, newest first, each with its segment count."""
    rows = conn.execute(
        "SELECT m.*, COUNT(s.id) AS segment_count "
        "FROM meetings m LEFT JOIN transcript_segments s ON s.meeting_id = m.id "
        "GROUP BY m.id ORDER BY m.started_at DESC"
    ).fetchall()
    return [_meeting(row) for row in rows]


def get_meeting(conn: sqlite3.Connection, meeting_id: int) -> Meeting | None:
    """One meeting by id, or ``None``."""
    row = conn.execute(
        "SELECT m.*, COUNT(s.id) AS segment_count "
        "FROM meetings m LEFT JOIN transcript_segments s ON s.meeting_id = m.id "
        "WHERE m.id = ? GROUP BY m.id",
        (meeting_id,),
    ).fetchone()
    return _meeting(row) if row is not None else None


def get_segments(conn: sqlite3.Connection, meeting_id: int) -> list[Segment]:
    """A meeting's transcript segments, in time order."""
    rows = conn.execute(
        "SELECT * FROM transcript_segments WHERE meeting_id = ? ORDER BY start_ms, id",
        (meeting_id,),
    ).fetchall()
    return [
        Segment(
            id=row["id"],
            meeting_id=row["meeting_id"],
            text=row["text"],
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
            language=row["language"],
            confidence=row["confidence"],
            speaker_id=row["speaker_id"],
        )
        for row in rows
    ]


def get_segments_by_ids(
    conn: sqlite3.Connection, ids: list[int]
) -> dict[int, Segment]:
    """Fetch segments by id, keyed by id (for mapping search hits to text)."""
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM transcript_segments WHERE id IN ({placeholders})", ids
    ).fetchall()
    return {
        row["id"]: Segment(
            id=row["id"],
            meeting_id=row["meeting_id"],
            text=row["text"],
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
            language=row["language"],
            confidence=row["confidence"],
            speaker_id=row["speaker_id"],
        )
        for row in rows
    }


def delete_meeting(conn: sqlite3.Connection, meeting_id: int) -> None:
    """Delete a meeting and (by cascade) its segments, speakers, summary."""
    conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
    conn.commit()


def set_meeting_status(conn: sqlite3.Connection, meeting_id: int, status: str) -> None:
    """Update a meeting's processing status (recording|processing|ready)."""
    conn.execute(
        "UPDATE meetings SET status = ? WHERE id = ?", (status, meeting_id)
    )
    conn.commit()


def create_speakers(
    conn: sqlite3.Connection, meeting_id: int, labels: list[str]
) -> dict[str, int]:
    """Create one speaker row per unique diarization label.

    Returns a mapping ``{diarization_label: speaker_id}``. Human labels
    ("Speaker 1", …) and colours are assigned in sorted label order, so the
    result is deterministic.
    """
    mapping: dict[str, int] = {}
    for index, label in enumerate(sorted(set(labels))):
        cursor = conn.execute(
            "INSERT INTO speakers (meeting_id, label, name, color) "
            "VALUES (?, ?, NULL, ?)",
            (
                meeting_id,
                f"Speaker {index + 1}",
                SPEAKER_COLORS[index % len(SPEAKER_COLORS)],
            ),
        )
        mapping[label] = int(cursor.lastrowid)
    conn.commit()
    return mapping


def get_speakers(conn: sqlite3.Connection, meeting_id: int) -> list[Speaker]:
    """A meeting's speakers, in creation order."""
    rows = conn.execute(
        "SELECT * FROM speakers WHERE meeting_id = ? ORDER BY id", (meeting_id,)
    ).fetchall()
    return [
        Speaker(
            id=row["id"],
            meeting_id=row["meeting_id"],
            label=row["label"],
            name=row["name"],
            color=row["color"],
            person_id=row["person_id"],
        )
        for row in rows
    ]


def set_segment_speaker(
    conn: sqlite3.Connection, segment_id: int, speaker_id: int | None
) -> None:
    """Attribute a transcript segment to a speaker."""
    conn.execute(
        "UPDATE transcript_segments SET speaker_id = ? WHERE id = ?",
        (speaker_id, segment_id),
    )
    conn.commit()


def update_segment_text(conn: sqlite3.Connection, segment_id: int, text: str) -> bool:
    """Correct a segment's transcript text; return False if it is unknown."""
    cursor = conn.execute(
        "UPDATE transcript_segments SET text = ? WHERE id = ?", (text, segment_id)
    )
    conn.commit()
    return cursor.rowcount > 0


def replace_action_items(
    conn: sqlite3.Connection, meeting_id: int, texts: list[str]
) -> None:
    """Replace a meeting's action items (called on every (re)summarise).

    Done-state carries over for items whose text is unchanged, so
    re-summarising doesn't un-check completed work.
    """
    done_by_text = {
        row["text"]: row["done"]
        for row in conn.execute(
            "SELECT text, done FROM action_items WHERE meeting_id = ?", (meeting_id,)
        )
    }
    conn.execute("DELETE FROM action_items WHERE meeting_id = ?", (meeting_id,))
    conn.executemany(
        "INSERT INTO action_items (meeting_id, text, done, position) "
        "VALUES (?, ?, ?, ?)",
        [
            (meeting_id, text, done_by_text.get(text, 0), position)
            for position, text in enumerate(texts)
        ],
    )
    conn.commit()


def get_action_items(conn: sqlite3.Connection) -> list[ActionItem]:
    """Every meeting's action items, newest meeting first, in summary order."""
    rows = conn.execute(
        "SELECT ai.id, ai.meeting_id, ai.text, ai.done, "
        "m.title AS meeting_title, m.started_at AS meeting_started_at "
        "FROM action_items ai JOIN meetings m ON m.id = ai.meeting_id "
        "ORDER BY m.started_at DESC, ai.position, ai.id"
    ).fetchall()
    return [
        ActionItem(
            id=row["id"],
            meeting_id=row["meeting_id"],
            meeting_title=row["meeting_title"],
            meeting_started_at=row["meeting_started_at"],
            text=row["text"],
            done=bool(row["done"]),
        )
        for row in rows
    ]


def set_action_item_done(conn: sqlite3.Connection, item_id: int, done: bool) -> bool:
    """Check or un-check one action item; return False if it is unknown."""
    cursor = conn.execute(
        "UPDATE action_items SET done = ? WHERE id = ?", (int(done), item_id)
    )
    conn.commit()
    return cursor.rowcount > 0


def _proposal(row: sqlite3.Row) -> Proposal:
    return Proposal(
        id=row["id"],
        meeting_id=row["meeting_id"],
        kind=row["kind"],
        target=row["target"],
        title=row["title"],
        body=row["body"],
        payload=json.loads(row["payload"] or "{}"),
        status=row["status"],
        external_ref=row["external_ref"],
        error=row["error"],
        created_at=row["created_at"],
        applied_at=row["applied_at"],
    )


def insert_proposals(
    conn: sqlite3.Connection,
    meeting_id: int,
    drafts: list[tuple[str, str, str, str, dict]],
) -> None:
    """Insert drafts as ``proposed`` rows.

    Each draft is ``(kind, target, title, body, payload)`` — primitives only,
    so this package stays independent of the integrations package.
    """
    conn.executemany(
        "INSERT INTO sync_proposals (meeting_id, kind, target, title, body, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (meeting_id, kind, target, title, body, json.dumps(payload))
            for kind, target, title, body, payload in drafts
        ],
    )
    conn.commit()


def get_proposals(conn: sqlite3.Connection, meeting_id: int) -> list[Proposal]:
    """A meeting's non-stale proposals, in creation order."""
    rows = conn.execute(
        "SELECT * FROM sync_proposals "
        "WHERE meeting_id = ? AND status != 'stale' ORDER BY id",
        (meeting_id,),
    ).fetchall()
    return [_proposal(row) for row in rows]


def get_proposal(conn: sqlite3.Connection, proposal_id: int) -> Proposal | None:
    row = conn.execute(
        "SELECT * FROM sync_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    return _proposal(row) if row else None


def update_proposal(
    conn: sqlite3.Connection,
    proposal_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    payload: dict | None = None,
) -> bool:
    """Edit an un-applied proposal's content; returns False if unknown/applied."""
    sets, args = [], []
    if title is not None:
        sets.append("title = ?")
        args.append(title)
    if body is not None:
        sets.append("body = ?")
        args.append(body)
    if payload is not None:
        sets.append("payload = ?")
        args.append(json.dumps(payload))
    if not sets:
        return True
    args.append(proposal_id)
    cursor = conn.execute(
        f"UPDATE sync_proposals SET {', '.join(sets)} "
        "WHERE id = ? AND status IN ('proposed', 'failed', 'skipped')",
        args,
    )
    conn.commit()
    return cursor.rowcount > 0


def set_proposal_status(
    conn: sqlite3.Connection, proposal_id: int, status: str
) -> bool:
    """Move a proposal between user-driven states (skip / un-skip)."""
    cursor = conn.execute(
        "UPDATE sync_proposals SET status = ? "
        "WHERE id = ? AND status != 'applied'",
        (status, proposal_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def set_proposal_result(
    conn: sqlite3.Connection,
    proposal_id: int,
    *,
    status: str,
    external_ref: str | None = None,
    error: str | None = None,
) -> None:
    """Record an apply attempt's outcome (``applied`` or ``failed``)."""
    conn.execute(
        "UPDATE sync_proposals SET status = ?, external_ref = ?, error = ?, "
        "applied_at = CASE WHEN ? = 'applied' THEN datetime('now') ELSE applied_at END "
        "WHERE id = ?",
        (status, external_ref, error, status, proposal_id),
    )
    conn.commit()


def mark_proposals_stale(conn: sqlite3.Connection, meeting_id: int) -> None:
    """Hide un-applied proposals before re-proposing (re-summarise path)."""
    conn.execute(
        "UPDATE sync_proposals SET status = 'stale' "
        "WHERE meeting_id = ? AND status IN ('proposed', 'failed', 'skipped')",
        (meeting_id,),
    )
    conn.commit()


def rename_speaker(conn: sqlite3.Connection, speaker_id: int, name: str) -> bool:
    """Set a speaker's display name; return False if the speaker is unknown."""
    cursor = conn.execute(
        "UPDATE speakers SET name = ? WHERE id = ?", (name, speaker_id)
    )
    conn.commit()
    return cursor.rowcount > 0


# ---- People (cross-meeting identity, anchored on email) ----------------------

#: Fields + joins shared by get_people / get_person. meeting_count and last_met
#: come from the attendee links; primary_email prefers the is_primary flag.
_PERSON_SELECT = (
    "SELECT p.id, p.display_name, p.notes, p.created_at, "
    "  (SELECT email FROM person_emails "
    "   WHERE person_id = p.id ORDER BY is_primary DESC, email LIMIT 1"
    "  ) AS primary_email, "
    "  COUNT(ma.meeting_id) AS meeting_count, "
    "  MAX(m.started_at) AS last_met "
    "FROM people p "
    "LEFT JOIN meeting_attendees ma ON ma.person_id = p.id "
    "LEFT JOIN meetings m ON m.id = ma.meeting_id "
)


def _person(row: sqlite3.Row) -> Person:
    return Person(
        id=row["id"],
        display_name=row["display_name"],
        primary_email=row["primary_email"],
        notes=row["notes"],
        meeting_count=row["meeting_count"],
        last_met=row["last_met"],
        created_at=row["created_at"],
    )


def upsert_person_by_email(
    conn: sqlite3.Connection, email: str, display_name: str | None = None
) -> int:
    """Resolve an email to its person, creating one if unseen; return the id.

    Emails are the cross-meeting anchor: stored lowercased, one email belongs
    to exactly one person. A later sighting with a display name fills in a
    person created without one, but never overwrites a name already set.
    """
    email = email.strip().lower()
    if not email:
        raise ValueError("Email must be non-empty.")
    row = conn.execute(
        "SELECT person_id FROM person_emails WHERE email = ?", (email,)
    ).fetchone()
    if row is not None:
        person_id = int(row["person_id"])
        if display_name:
            conn.execute(
                "UPDATE people SET display_name = ? "
                "WHERE id = ? AND display_name IS NULL",
                (display_name, person_id),
            )
            conn.commit()
        return person_id
    cursor = conn.execute(
        "INSERT INTO people (display_name) VALUES (?)", (display_name,)
    )
    person_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO person_emails (email, person_id, is_primary) VALUES (?, ?, 1)",
        (email, person_id),
    )
    conn.commit()
    return person_id


def get_people(conn: sqlite3.Connection) -> list[Person]:
    """Everyone, most recently met first (never-met people last)."""
    rows = conn.execute(
        _PERSON_SELECT + "GROUP BY p.id ORDER BY (last_met IS NULL), last_met DESC, p.id"
    ).fetchall()
    return [_person(row) for row in rows]


def get_person(conn: sqlite3.Connection, person_id: int) -> Person | None:
    """One person by id, or ``None``."""
    row = conn.execute(
        _PERSON_SELECT + "WHERE p.id = ? GROUP BY p.id", (person_id,)
    ).fetchone()
    return _person(row) if row is not None else None


def set_person_notes(conn: sqlite3.Connection, person_id: int, notes: str) -> bool:
    """Replace a person's notes; return False if the person is unknown."""
    cursor = conn.execute(
        "UPDATE people SET notes = ? WHERE id = ?", (notes, person_id)
    )
    conn.commit()
    return cursor.rowcount > 0


def add_meeting_attendee(
    conn: sqlite3.Connection, meeting_id: int, person_id: int, source: str = "calendar"
) -> None:
    """Link a person to a meeting they attended (idempotent)."""
    conn.execute(
        "INSERT OR IGNORE INTO meeting_attendees (meeting_id, person_id, source) "
        "VALUES (?, ?, ?)",
        (meeting_id, person_id, source),
    )
    conn.commit()


def get_meeting_ids_for_person(
    conn: sqlite3.Connection, person_id: int
) -> list[int]:
    """Ids of the meetings a person attended, newest first."""
    rows = conn.execute(
        "SELECT ma.meeting_id FROM meeting_attendees ma "
        "JOIN meetings m ON m.id = ma.meeting_id "
        "WHERE ma.person_id = ? ORDER BY m.started_at DESC, ma.meeting_id",
        (person_id,),
    ).fetchall()
    return [int(row["meeting_id"]) for row in rows]


def link_speaker_to_person(
    conn: sqlite3.Connection, speaker_id: int, person_id: int | None
) -> bool:
    """Bridge a per-meeting speaker to a person (``None`` unlinks); False if
    the speaker is unknown."""
    cursor = conn.execute(
        "UPDATE speakers SET person_id = ? WHERE id = ?", (person_id, speaker_id)
    )
    conn.commit()
    return cursor.rowcount > 0


def merge_people(conn: sqlite3.Connection, keep_id: int, drop_id: int) -> None:
    """Fold ``drop_id`` into ``keep_id``, atomically.

    Repoints emails, attendee links, and speaker bridges; unions notes; keeps
    ``keep``'s display name (falling back to ``drop``'s); deletes the dropped
    row. Runs in one transaction — a failure part-way leaves both people
    untouched. Overlapping attendee rows (both people in the same meeting)
    collapse into one instead of violating the primary key.
    """
    if keep_id == drop_id:
        raise ValueError("Cannot merge a person into themselves.")
    with conn:  # BEGIN … COMMIT (or ROLLBACK on error)
        rows = {
            row["id"]: (row["display_name"], row["notes"])
            for row in conn.execute(
                "SELECT id, display_name, notes FROM people WHERE id IN (?, ?)",
                (keep_id, drop_id),
            )
        }
        if keep_id not in rows or drop_id not in rows:
            raise ValueError("Both people must exist to merge.")
        # Moved emails lose their primary flag — keep's primary stays primary.
        conn.execute(
            "UPDATE person_emails SET person_id = ?, is_primary = 0 "
            "WHERE person_id = ?",
            (keep_id, drop_id),
        )
        # Collapse meetings both attended, then repoint the rest.
        conn.execute(
            "DELETE FROM meeting_attendees WHERE person_id = ? AND meeting_id IN "
            "(SELECT meeting_id FROM meeting_attendees WHERE person_id = ?)",
            (drop_id, keep_id),
        )
        conn.execute(
            "UPDATE meeting_attendees SET person_id = ? WHERE person_id = ?",
            (keep_id, drop_id),
        )
        conn.execute(
            "UPDATE speakers SET person_id = ? WHERE person_id = ?",
            (keep_id, drop_id),
        )
        keep_name, keep_notes = rows[keep_id]
        drop_name, drop_notes = rows[drop_id]
        notes = (
            f"{keep_notes}\n\n{drop_notes}"
            if keep_notes and drop_notes
            else keep_notes or drop_notes
        )
        conn.execute(
            "UPDATE people SET display_name = ?, notes = ? WHERE id = ?",
            (keep_name or drop_name, notes, keep_id),
        )
        conn.execute("DELETE FROM people WHERE id = ?", (drop_id,))


def set_meeting_title(conn: sqlite3.Connection, meeting_id: int, title: str) -> None:
    """Replace a meeting's title (LLM title supersedes the date-based one)."""
    conn.execute("UPDATE meetings SET title = ? WHERE id = ?", (title, meeting_id))
    conn.commit()


def save_summary(
    conn: sqlite3.Connection,
    meeting_id: int,
    *,
    summary: str,
    key_points: list[str],
    action_items: list[str],
    decisions: list[str],
    open_questions: list[str],
) -> None:
    """Insert or replace a meeting's summary (one per meeting)."""
    conn.execute(
        "INSERT INTO summaries "
        "(meeting_id, summary, key_points, action_items, decisions, open_questions) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(meeting_id) DO UPDATE SET "
        "summary = excluded.summary, key_points = excluded.key_points, "
        "action_items = excluded.action_items, decisions = excluded.decisions, "
        "open_questions = excluded.open_questions",
        (
            meeting_id,
            summary,
            json.dumps(key_points),
            json.dumps(action_items),
            json.dumps(decisions),
            json.dumps(open_questions),
        ),
    )
    conn.commit()


def get_summary(conn: sqlite3.Connection, meeting_id: int) -> StoredSummary | None:
    """A meeting's summary, or ``None`` if not yet generated."""
    row = conn.execute(
        "SELECT * FROM summaries WHERE meeting_id = ?", (meeting_id,)
    ).fetchone()
    if row is None:
        return None
    return StoredSummary(
        summary=row["summary"] or "",
        key_points=json.loads(row["key_points"] or "[]"),
        action_items=json.loads(row["action_items"] or "[]"),
        decisions=json.loads(row["decisions"] or "[]"),
        open_questions=json.loads(row["open_questions"] or "[]"),
    )


def _meeting(row: sqlite3.Row) -> Meeting:
    return Meeting(
        id=row["id"],
        title=row["title"],
        source=row["source"],
        status=row["status"],
        wav_path=row["wav_path"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        segment_count=row["segment_count"],
    )
