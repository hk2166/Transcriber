"""Persistence for Confab — plain sqlite3, no ORM.

``connect(path)`` opens a database and applies migrations; the ``repository``
functions do typed CRUD over it.
"""

from packages.storage.db import connect
from packages.storage.repository import (
    ActionItem,
    Meeting,
    Segment,
    Speaker,
    StoredSummary,
    create_meeting,
    create_speakers,
    delete_meeting,
    end_meeting,
    get_action_items,
    get_meeting,
    get_meetings,
    get_segments,
    get_segments_by_ids,
    get_speakers,
    get_summary,
    insert_segment,
    rename_speaker,
    replace_action_items,
    save_summary,
    set_action_item_done,
    set_meeting_status,
    set_meeting_title,
    set_segment_speaker,
    update_segment_text,
)

__all__ = [
    "ActionItem",
    "Meeting",
    "Segment",
    "Speaker",
    "StoredSummary",
    "connect",
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
