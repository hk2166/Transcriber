"""The shared, self-contained export model.

The backend assembles a :class:`MeetingExport` from storage; the format
renderers consume only this — so the export package stays independent of the
database schema.
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["ExportSegment", "ExportSummary", "MeetingExport"]


class ExportSegment(BaseModel):
    start_ms: int
    end_ms: int
    speaker: str | None
    text: str


class ExportSummary(BaseModel):
    summary: str
    key_points: list[str] = []
    action_items: list[str] = []
    decisions: list[str] = []
    open_questions: list[str] = []


class MeetingExport(BaseModel):
    title: str
    started_at: str
    source: str
    speakers: list[str] = []
    summary: ExportSummary | None = None
    segments: list[ExportSegment] = []


def format_timestamp(ms: int) -> str:
    """``mm:ss`` (or ``h:mm:ss`` past an hour) for a millisecond offset."""
    total_seconds = ms // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
