"""Persistence for MeetingMind — plain sqlite3, no ORM.

``connect(path)`` opens a database and applies migrations; the ``repository``
functions do typed CRUD over it.
"""

from packages.storage.db import connect
from packages.storage.repository import (
    Meeting,
    Segment,
    Speaker,
    StoredSummary,
    create_meeting,
    create_speakers,
    delete_meeting,
    end_meeting,
    get_meeting,
    get_meetings,
    get_segments,
    get_speakers,
    get_summary,
    insert_segment,
    rename_speaker,
    save_summary,
    set_meeting_status,
    set_meeting_title,
    set_segment_speaker,
)

__all__ = [
    "Meeting",
    "Segment",
    "Speaker",
    "StoredSummary",
    "connect",
    "create_meeting",
    "create_speakers",
    "delete_meeting",
    "end_meeting",
    "get_meeting",
    "get_meetings",
    "get_segments",
    "get_speakers",
    "get_summary",
    "insert_segment",
    "rename_speaker",
    "save_summary",
    "set_meeting_status",
    "set_meeting_title",
    "set_segment_speaker",
]
