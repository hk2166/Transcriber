"""RAG chat over a meeting's transcript, streamed as Server-Sent Events.

Events: ``sources`` (retrieved passages) → many ``token`` → ``done`` (or
``error`` if Ollama is down). Runs in a threadpool (sync endpoint + sync
generator), so the blocking LLM stream never touches the event loop.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import llm
import search_index
from database import get_db
from packages.intelligence import MeetingRAG, OllamaUnavailable
from packages.storage import get_meeting, get_segments

router = APIRouter(prefix="/meetings", tags=["chat"])


class ChatRequest(BaseModel):
    question: str


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/{meeting_id}/chat")
def chat(meeting_id: int, request: ChatRequest) -> StreamingResponse:
    """Answer a question about a meeting, grounded in its transcript."""
    if get_meeting(get_db(), meeting_id) is None:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found.")

    segments = get_segments(get_db(), meeting_id)
    try:
        client = llm.current_client()
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    rag = MeetingRAG(client, search_index.get_embedder())
    retrieved = rag.retrieve(request.question, [(s.id, s.text) for s in segments])

    def stream():
        yield _sse(
            "sources",
            {
                "sources": [
                    {"segment_id": r.segment_id, "text": r.text, "score": r.score}
                    for r in retrieved
                ]
            },
        )
        try:
            for token in rag.chat_stream(request.question, retrieved):
                yield _sse("token", {"text": token})
        except OllamaUnavailable as exc:
            yield _sse("error", {"message": str(exc)})
        yield _sse("done", {})

    return StreamingResponse(stream(), media_type="text/event-stream")
