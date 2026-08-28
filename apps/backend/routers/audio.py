"""Audio session endpoints: start/stop + live PCM WebSocket stream."""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from packages.audio import AudioCapture
from sessions import AudioSource, SessionConflict, SessionNotFound, manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["audio"])


class StartRequest(BaseModel):
    source: AudioSource = "both"
    vad_enabled: bool = True


class StartResponse(BaseModel):
    session_id: str
    source: AudioSource
    system_available: bool
    vad_enabled: bool
    wav_path: str


class StopResponse(BaseModel):
    session_id: str
    duration_seconds: float
    frames_written: int
    wav_path: str


class PauseResponse(BaseModel):
    session_id: str
    paused: bool


@router.post("/start", response_model=StartResponse)
async def start_session(request: StartRequest) -> StartResponse:
    """Start a recording session. 409 if one is active, 503 if the
    requested audio device is unavailable."""
    try:
        session = manager.start(request.source, vad_enabled=request.vad_enabled)
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return StartResponse(
        session_id=session.session_id,
        source=session.source,
        system_available=session.system_available,
        vad_enabled=session.vad_enabled,
        wav_path=str(session.recorder.path),
    )


@router.post("/stop", response_model=StopResponse)
async def stop_session() -> StopResponse:
    """Stop the active session. 409 if none is running."""
    try:
        session = await manager.stop()
    except SessionNotFound as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StopResponse(
        session_id=session.session_id,
        duration_seconds=session.recorder.duration_seconds,
        frames_written=session.recorder.frames_written,
        wav_path=str(session.recorder.path),
    )


@router.post("/pause", response_model=PauseResponse)
async def pause_session() -> PauseResponse:
    """Pause the active session. 409 if none is running."""
    session = manager.active
    if session is None:
        raise HTTPException(status_code=409, detail="No active session to pause.")
    session.pause()
    return PauseResponse(session_id=session.session_id, paused=True)


@router.post("/resume", response_model=PauseResponse)
async def resume_session() -> PauseResponse:
    """Resume a paused session. 409 if none is running."""
    session = manager.active
    if session is None:
        raise HTTPException(status_code=409, detail="No active session to resume.")
    session.resume()
    return PauseResponse(session_id=session.session_id, paused=False)


@router.websocket("/stream/{session_id}")
async def stream_audio(websocket: WebSocket, session_id: str) -> None:
    """Stream base64-encoded float32 PCM blocks until the session stops."""
    await websocket.accept()
    try:
        session = manager.get(session_id)
    except SessionNotFound as exc:
        await websocket.close(code=4404, reason=str(exc))
        return

    await websocket.send_json(
        {
            "type": "hello",
            "session_id": session.session_id,
            "sample_rate": AudioCapture.SAMPLE_RATE,
            "channels": AudioCapture.CHANNELS,
            "encoding": "float32le",
        }
    )
    try:
        while True:
            block = await session.stream_queue.get()
            if block is None:
                await websocket.send_json({"type": "end"})
                break
            await websocket.send_json(
                {
                    "type": "audio",
                    "frames": len(block),
                    "speech": session.speech_active,
                    "data": base64.b64encode(block.tobytes()).decode("ascii"),
                }
            )
    except WebSocketDisconnect:
        logger.info("WebSocket client left session %s.", session_id)
