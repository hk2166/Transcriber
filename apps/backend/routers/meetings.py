"""Meeting endpoints: list, fetch, segments, delete."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from database import get_db
from packages.storage import (
    Meeting,
    Segment,
    delete_meeting,
    get_meeting,
    get_meetings,
    get_segments,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _require_meeting(meeting_id: int) -> Meeting:
    meeting = get_meeting(get_db(), meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found.")
    return meeting


@router.get("")
def list_meetings() -> list[Meeting]:
    """All meetings, newest first."""
    return get_meetings(get_db())


@router.get("/{meeting_id}")
def read_meeting(meeting_id: int) -> Meeting:
    """One meeting, or 404."""
    return _require_meeting(meeting_id)


@router.get("/{meeting_id}/segments")
def read_segments(meeting_id: int) -> list[Segment]:
    """A meeting's transcript segments, in time order (404 if unknown)."""
    _require_meeting(meeting_id)
    return get_segments(get_db(), meeting_id)


@router.delete("/{meeting_id}")
def remove_meeting(meeting_id: int) -> dict[str, bool]:
    """Delete a meeting, its segments (cascade), and its WAV file."""
    meeting = _require_meeting(meeting_id)
    if meeting.wav_path:
        Path(meeting.wav_path).unlink(missing_ok=True)
    delete_meeting(get_db(), meeting_id)
    return {"deleted": True}
