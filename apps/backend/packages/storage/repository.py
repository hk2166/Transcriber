"""Typed CRUD over the meetings schema.

Plain functions taking a ``sqlite3.Connection`` — no ORM, no globals. Read
results come back as dataclasses; writes take primitives so this package
stays independent of the transcription package.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

__all__ = [
    "Meeting",
    "Segment",
    "create_meeting",
    "delete_meeting",
    "end_meeting",
    "get_meeting",
    "get_meetings",
    "get_segments",
    "insert_segment",
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


def delete_meeting(conn: sqlite3.Connection, meeting_id: int) -> None:
    """Delete a meeting and (by cascade) its segments, speakers, summary."""
    conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
    conn.commit()


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
