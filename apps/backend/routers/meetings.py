"""Meeting endpoints: list, fetch, segments, delete."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

import postprocess_job
from database import get_db
from packages.storage import (
    Meeting,
    Segment,
    Speaker,
    StoredSummary,
    delete_meeting,
    get_meeting,
    get_meetings,
    get_segments,
    get_speakers,
    get_summary,
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


@router.get("/{meeting_id}/speakers")
def read_speakers(meeting_id: int) -> list[Speaker]:
    """A meeting's speakers (404 if the meeting is unknown)."""
    _require_meeting(meeting_id)
    return get_speakers(get_db(), meeting_id)


@router.get("/{meeting_id}/summary")
def read_summary(meeting_id: int) -> StoredSummary:
    """A meeting's summary; 404 if it hasn't been generated yet."""
    _require_meeting(meeting_id)
    summary = get_summary(get_db(), meeting_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="No summary for this meeting yet.")
    return summary


@router.post("/{meeting_id}/summarize")
def trigger_summary(meeting_id: int) -> dict[str, str]:
    """Regenerate the summary in the background."""
    _require_meeting(meeting_id)
    postprocess_job.schedule_summary(meeting_id)
    return {"status": "processing"}


@router.delete("/{meeting_id}")
def remove_meeting(meeting_id: int) -> dict[str, bool]:
    """Delete a meeting, its segments (cascade), and its WAV file."""
    meeting = _require_meeting(meeting_id)
    if meeting.wav_path:
        Path(meeting.wav_path).unlink(missing_ok=True)
    delete_meeting(get_db(), meeting_id)
    import search_index

    search_index.remove_meeting(meeting_id)
    return {"deleted": True}
