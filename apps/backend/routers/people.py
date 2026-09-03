"""People: roster, detail, notes, merge, and on-demand prep (SSE).

Prep is a computed view — nothing it generates is stored. The stream is the
same shape as meeting chat (``routers/chat.py``): a sync endpoint whose
generator runs in the threadpool, so the blocking LLM stream never touches
the event loop.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import llm
import search_index
from database import get_db
from packages.intelligence import OllamaUnavailable
from packages.intelligence.prep import format_date, stream_prep
from packages.storage import (
    Person,
    get_meeting,
    get_meeting_ids_for_person,
    get_people,
    get_person,
    merge_people,
    update_person,
)

router = APIRouter(prefix="/people", tags=["people"])


class PersonPatch(BaseModel):
    display_name: str | None = None
    notes: str | None = None


class MergeRequest(BaseModel):
    keep_id: int
    drop_id: int


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _require_person(person_id: int) -> Person:
    person = get_person(get_db(), person_id)
    if person is None:
        raise HTTPException(status_code=404, detail=f"Person {person_id} not found.")
    return person


@router.get("")
def roster() -> list[Person]:
    """Everyone, most recently met first."""
    return get_people(get_db())


@router.post("/merge")
def merge(request: MergeRequest) -> dict[str, int]:
    """Fold ``drop_id`` into ``keep_id`` (emails, meetings, speaker bridges, notes)."""
    try:
        merge_people(get_db(), request.keep_id, request.drop_id)
    except ValueError as exc:
        status = 404 if "exist" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"kept": request.keep_id}


@router.get("/{person_id}")
def detail(person_id: int) -> dict:
    """A person plus the meetings they attended."""
    person = _require_person(person_id)
    db = get_db()
    meetings = []
    for meeting_id in get_meeting_ids_for_person(db, person_id):
        meeting = get_meeting(db, meeting_id)
        if meeting is not None:
            meetings.append(
                {"id": meeting.id, "title": meeting.title, "started_at": meeting.started_at}
            )
    return {"person": person, "meetings": meetings}


@router.patch("/{person_id}")
def patch(person_id: int, body: PersonPatch) -> Person:
    """Update display name and/or notes; 404 if unknown, 422 if nothing given."""
    if body.display_name is None and body.notes is None:
        raise HTTPException(status_code=422, detail="Nothing to update.")
    _require_person(person_id)
    update_person(get_db(), person_id, display_name=body.display_name, notes=body.notes)
    return get_person(get_db(), person_id)  # type: ignore[return-value]


@router.get("/{person_id}/prep")
def prep(person_id: int) -> StreamingResponse:
    """Stream the prep briefing: per lens ``lens`` → ``sources`` → ``token``…
    → ``lens_done`` (or ``lens_empty``), then ``done``. Never persisted."""
    person = _require_person(person_id)
    db = get_db()
    meeting_ids = get_meeting_ids_for_person(db, person_id)
    try:
        client = llm.current_client()
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    name = person.display_name or person.primary_email or f"person {person_id}"
    dates: dict[int, str] = {}

    def meeting_date(meeting_id: int) -> str:
        if meeting_id not in dates:
            meeting = get_meeting(db, meeting_id)
            dates[meeting_id] = format_date(meeting.started_at if meeting else None)
        return dates[meeting_id]

    def stream():
        try:
            for event in stream_prep(
                name,
                meeting_ids,
                retrieve=search_index.search_meetings,
                client=client,
                meeting_date=meeting_date,
            ):
                yield _sse(event.kind, event.data)
        except OllamaUnavailable as exc:
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})

    return StreamingResponse(stream(), media_type="text/event-stream")
