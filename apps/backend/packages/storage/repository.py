"""Typed CRUD over the meetings schema.

Plain functions taking a ``sqlite3.Connection`` — no ORM, no globals. Read
results come back as dataclasses; writes take primitives so this package
stays independent of the transcription package.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

__all__ = [
    "ActionItem",
    "Meeting",
    "Segment",
    "Speaker",
    "StoredSummary",
    "create_meeting",
    "create_speakers",
    "delete_meeting",
    "end_meeting",
    "get_action_items",
    "get_meeting",
    "get_meetings",
    "get_segments",
    "get_segments_by_ids",
    "get_speakers",
    "get_summary",
    "insert_segment",
    "rename_speaker",
    "replace_action_items",
    "save_summary",
    "set_action_item_done",
    "set_meeting_status",
    "set_meeting_title",
    "set_segment_speaker",
    "update_segment_text",
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


def rename_speaker(conn: sqlite3.Connection, speaker_id: int, name: str) -> bool:
    """Set a speaker's display name; return False if the speaker is unknown."""
    cursor = conn.execute(
        "UPDATE speakers SET name = ? WHERE id = ?", (name, speaker_id)
    )
    conn.commit()
    return cursor.rowcount > 0


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
