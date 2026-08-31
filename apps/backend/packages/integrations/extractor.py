"""LLM-assisted extraction of calendar-worthy follow-ups.

One structured-output call against the user's configured summary LLM (passed
in — this package never builds clients). "Next Thursday at 2" resolves against
the meeting's start time. Anything malformed is dropped, never guessed: a bad
extraction that books a wrong meeting is worse than no extraction.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

__all__ = ["extract_events"]

MAX_EVENTS = 3
MAX_TITLE = 80
#: Events further out than this are almost certainly mis-parsed dates.
MAX_HORIZON_DAYS = 366

_SYSTEM = (
    "You extract calendar events from meeting notes. Reply with ONLY a JSON "
    'object: {"events": [{"title": str, "start_iso": str, "duration_min": int}]}. '
    "Include ONLY follow-ups with a clearly stated date or day (e.g. 'next "
    "Thursday at 2pm', 'September 3rd'). Resolve relative dates against the "
    "meeting start time given. Use ISO 8601 for start_iso. If no time was "
    "stated, use 10:00. If nothing has a clear date, return {\"events\": []}. "
    "Never invent meetings."
)


def extract_events(client, ctx_title: str, summary: str, transcript_tail: str,
                   started_at: str) -> list[dict]:
    """Return validated event dicts: {"title", "start_iso", "duration_min"}.

    ``client`` is any intelligence client (``complete(prompt, system, format)``).
    Raises nothing — an unavailable/garbled LLM yields ``[]`` (callers already
    treat extraction as best-effort).
    """
    prompt = (
        f"Meeting: {ctx_title}\n"
        f"Meeting start: {started_at}\n\n"
        f"Summary:\n{summary}\n\n"
        f"Transcript (tail):\n{transcript_tail[-4000:]}"
    )
    try:
        raw = client.complete(prompt, system=_SYSTEM, format="json")
        data = json.loads(raw)
    except Exception:
        logger.info("Event extraction unavailable — skipping calendar proposals.")
        return []
    return _validate(data.get("events"), started_at)


def _validate(events, started_at: str) -> list[dict]:
    if not isinstance(events, list):
        return []
    try:
        meeting_start = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        meeting_start = datetime.now()
    horizon = meeting_start + timedelta(days=MAX_HORIZON_DAYS)

    valid: list[dict] = []
    for event in events[: MAX_EVENTS * 2]:
        if not isinstance(event, dict):
            continue
        title = str(event.get("title") or "").strip()[:MAX_TITLE]
        try:
            start = datetime.fromisoformat(str(event.get("start_iso")))
        except (TypeError, ValueError):
            continue
        if not title or start > horizon:
            continue
        try:
            duration = int(event.get("duration_min") or 30)
        except (TypeError, ValueError):
            duration = 30
        valid.append(
            {
                "title": title,
                "start_iso": start.isoformat(timespec="minutes"),
                "duration_min": max(5, min(duration, 8 * 60)),
            }
        )
        if len(valid) == MAX_EVENTS:
            break
    return valid
