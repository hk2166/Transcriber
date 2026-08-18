"""Structured meeting summary + title from a transcript, via one LLM call each."""

from __future__ import annotations

import logging

from pydantic import BaseModel, ValidationError

from packages.intelligence.client import OllamaClient

logger = logging.getLogger(__name__)

__all__ = ["MeetingSummary", "generate_title", "summarize"]

#: Transcript is truncated to this many characters to bound context/latency.
MAX_TRANSCRIPT_CHARS = 12_000


class MeetingSummary(BaseModel):
    summary: str
    key_points: list[str] = []
    action_items: list[str] = []
    decisions: list[str] = []
    open_questions: list[str] = []


_SUMMARY_SYSTEM = (
    "You are a meeting-notes assistant. Read the transcript and return a "
    "concise, accurate JSON summary. Use only information present in the "
    "transcript — never invent action items or decisions. Empty lists are "
    "fine when a section has nothing."
)

_SUMMARY_PROMPT = (
    "Summarise this meeting transcript.\n\n"
    "Return JSON with these keys:\n"
    "- summary: 2–4 sentence overview\n"
    "- key_points: main discussion points\n"
    "- action_items: concrete tasks someone agreed to do\n"
    "- decisions: decisions that were made\n"
    "- open_questions: unresolved questions\n\n"
    "Transcript:\n{transcript}"
)

_TITLE_SYSTEM = "You name meetings. Reply with only a short title, 3–7 words, no quotes."
_TITLE_PROMPT = "Give a short, specific title for this meeting:\n\n{transcript}"


def summarize(client: OllamaClient, transcript: str) -> MeetingSummary:
    """One structured call → validated summary, with a single retry on bad JSON."""
    text = transcript[:MAX_TRANSCRIPT_CHARS]
    schema = MeetingSummary.model_json_schema()
    prompt = _SUMMARY_PROMPT.format(transcript=text)

    last_error: Exception | None = None
    for attempt in range(2):
        raw = client.complete(prompt, system=_SUMMARY_SYSTEM, format=schema)
        try:
            return MeetingSummary.model_validate_json(raw)
        except ValidationError as exc:
            last_error = exc
            logger.warning("Summary JSON invalid (attempt %d): %s", attempt + 1, exc)
    raise ValueError(f"Model did not return a valid summary: {last_error}")


def generate_title(client: OllamaClient, transcript: str) -> str:
    """Short LLM title (replaces the date-based auto-title)."""
    text = transcript[: MAX_TRANSCRIPT_CHARS // 3]
    reply = client.complete(_TITLE_PROMPT.format(transcript=text), system=_TITLE_SYSTEM)
    return reply.strip().strip('"').strip()[:80]
