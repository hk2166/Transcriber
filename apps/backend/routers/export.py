"""Meeting export endpoint — build the export model from storage, render, serve."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from database import get_db
from packages.export import FORMATS, ExportSegment, ExportSummary, MeetingExport
from packages.storage import get_meeting, get_segments, get_speakers, get_summary

router = APIRouter(prefix="/meetings", tags=["export"])


def _build_export(meeting_id: int) -> MeetingExport:
    db = get_db()
    meeting = get_meeting(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found.")

    names = {s.id: (s.name or s.label) for s in get_speakers(db, meeting_id)}
    segments = [
        ExportSegment(
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            speaker=names.get(s.speaker_id) if s.speaker_id else None,
            text=s.text,
        )
        for s in get_segments(db, meeting_id)
    ]

    stored = get_summary(db, meeting_id)
    summary = ExportSummary(**vars(stored)) if stored else None

    return MeetingExport(
        title=meeting.title,
        started_at=meeting.started_at.replace("T", " ")[:16],
        source=meeting.source,
        speakers=list(names.values()),
        summary=summary,
        segments=segments,
    )


def _filename(title: str, ext: str) -> str:
    base = re.sub(r"[^\w\- ]", "", title).strip() or "meeting"
    return f"{base}.{ext}"


@router.get("/{meeting_id}/export/{fmt}")
def export_meeting(meeting_id: int, fmt: str) -> Response:
    """Render a meeting to ``fmt`` (markdown|json|pdf|docx) as a download."""
    export_format = FORMATS.get(fmt)
    if export_format is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown format {fmt!r}; expected one of {sorted(FORMATS)}.",
        )

    export = _build_export(meeting_id)
    blob = export_format.render(export)
    filename = _filename(export.title, export_format.ext)
    return Response(
        content=blob,
        media_type=export_format.mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
