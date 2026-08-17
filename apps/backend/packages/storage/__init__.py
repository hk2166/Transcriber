"""Persistence for MeetingMind — plain sqlite3, no ORM.

``connect(path)`` opens a database and applies migrations; the ``repository``
functions do typed CRUD over it.
"""

from packages.storage.db import connect
from packages.storage.repository import (
    Meeting,
    Segment,
    create_meeting,
    delete_meeting,
    end_meeting,
    get_meeting,
    get_meetings,
    get_segments,
    insert_segment,
)

__all__ = [
    "Meeting",
    "Segment",
    "connect",
    "create_meeting",
    "delete_meeting",
    "end_meeting",
    "get_meeting",
    "get_meetings",
    "get_segments",
    "insert_segment",
]
