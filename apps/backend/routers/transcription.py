"""Transcription endpoint: live TranscriptSegment stream over WebSocket."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from sessions import SessionNotFound, manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcription", tags=["transcription"])

@router.websocket("/stream/{session_id}")
async def stream_transcription(websocket: WebSocket, session_id: str) -> None:
    """Emit TranscriptSegment JSON as speech is transcribed. until the session ends or the client disconnects."""
    await websocket.accept()
    try:
        session = manager.get(session_id)
    except SessionNotFound as exc:
        logger.warning("Transcription stream for unknown session %s", session_id)
        await websocket.close(code=4404, reason=str(exc))
        return

    await websocket.send_json({"type": "hello", "session_id": session.session_id})
    try:
        while True:
            transcript = await session.transcript_queue.get()
            if transcript is None:
                await websocket.send_json({"type": "end"})
                break
            await websocket.send_json(
                {
                    "type": "transcript",
                    "text": transcript.text,
                    "start_ms": transcript.start_ms,
                    "end_ms": transcript.end_ms,
                    "language": transcript.language,
                    "confidence": round(transcript.confidence, 3),
                }
            )
    except WebSocketDisconnect:
        logger.info("WebSocket client left transcription stream for session %s.", session_id)