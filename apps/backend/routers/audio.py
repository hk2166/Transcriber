"""Audio session endpoints: start/stop + live PCM WebSocket stream."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import tempfile
from datetime import datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

import postprocess_job
from database import get_db
from packages.audio import AudioCapture, decode_to_wav, default_recordings_dir, routing
from packages.storage import Meeting, create_meeting, end_meeting, get_meeting, set_meeting_title
from sessions import AudioSource, SessionConflict, SessionNotFound, manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["audio"])


class RoutingStatus(BaseModel):
    blackhole_present: bool
    routed: bool
    output_name: str | None
    confab_aggregate_active: bool


@router.get("/routing", response_model=RoutingStatus)
def routing_status() -> RoutingStatus:
    """Is system audio actually reaching BlackHole (installed ≠ routed)?"""
    return RoutingStatus(**routing.status())


@router.post("/routing/enable", response_model=RoutingStatus)
def routing_enable() -> RoutingStatus:
    """One click: pair the current output with BlackHole and switch to it."""
    try:
        routing.enable()
    except routing.RoutingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RoutingStatus(**routing.status())


@router.post("/routing/disable", response_model=RoutingStatus)
def routing_disable() -> RoutingStatus:
    """Restore the plain output device and remove Confab's Multi-Output."""
    try:
        routing.disable()
    except routing.RoutingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RoutingStatus(**routing.status())


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


def _save_upload(upload: UploadFile, dst_path: str) -> None:
    """Stream the upload to disk in chunks (never load the whole file in RAM)."""
    with open(dst_path, "wb") as out:
        shutil.copyfileobj(upload.file, out, length=1024 * 1024)


@router.post("/import", response_model=Meeting)
async def import_audio(file: Annotated[UploadFile, File()]) -> Meeting:
    """Import an audio/video file as a meeting: decode → transcribe → diarize →
    summarize → index → propose, exactly like a recording. Returns the meeting
    row in ``processing`` status; the UI polls it to ``ready``."""
    suffix = os.path.splitext(file.filename or "")[1][:16]
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(tmp_fd)
    wav_path = default_recordings_dir() / f"{uuid4().hex}.wav"
    try:
        await asyncio.to_thread(_save_upload, file, tmp_path)
        # Decode any PyAV-readable audio/video to the 16 kHz mono WAV the
        # pipeline expects; an undecodable file (no audio track) is a 400.
        try:
            await asyncio.to_thread(decode_to_wav, tmp_path, str(wav_path))
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="Couldn't read audio from that file. Use an audio or "
                "video file with an audio track (mp3, m4a, wav, mp4, mov…).",
            ) from exc
    finally:
        os.unlink(tmp_path)

    db = get_db()
    meeting_id = create_meeting(
        db, source="import", wav_path=str(wav_path), started_at=datetime.now()
    )
    title = os.path.splitext(os.path.basename(file.filename or ""))[0] or "Imported recording"
    set_meeting_title(db, meeting_id, title)
    end_meeting(db, meeting_id, ended_at=datetime.now(), status="processing")
    postprocess_job.schedule_import(meeting_id, str(wav_path))
    logger.info("Imported %r as meeting %d.", file.filename, meeting_id)
    return get_meeting(db, meeting_id)
