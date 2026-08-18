"""In-memory audio session management.

One active session at a time (v1). A session owns the capture pipeline:
capture → recorder tee (always, lossless) + bounded stream queue (WebSocket).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Literal

import numpy as np

import diarization_job
from database import get_db
from packages.audio import (
    MicrophoneCapture,
    MixedAudioCapture,
    SessionRecorder,
    SystemAudioCapture,
    default_recordings_dir,
)
from packages.storage import create_meeting, end_meeting, insert_segment
from packages.transcription import TranscriptSegment, WhisperTranscriber
from packages.vad import SileroVAD, SpeechSegment, SpeechSegmenter

logger = logging.getLogger(__name__)

__all__ = [
    "AudioSession",
    "AudioSource",
    "SessionConflict",
    "SessionNotFound",
    "manager",
]

AudioSource = Literal["mic", "system", "both"]

#: Stream buffer: 256 blocks ≈ 16 s of audio. Overflow drops WebSocket
#: audio only — the recorder tee always receives every block.
STREAM_QUEUE_MAXSIZE = 256

WHISPER_MODEL_SIZE = "small"

_transcriber: WhisperTranscriber | None = None
_transcriber_lock = threading.Lock()

def get_transcriber() -> WhisperTranscriber:
    """
    Return the process-wide Whisper model, loading it once on first use.

    Blocking (model load is multi-second) — call it from a worker thread via
    ``asyncio.to_thread``, never directly on the event loop.
    """
    global _transcriber
    with _transcriber_lock:
        if _transcriber is None:
            _transcriber = WhisperTranscriber(model_size=WHISPER_MODEL_SIZE)
        return _transcriber
    


class SessionConflict(RuntimeError):
    """Raised when starting a session while another one is active."""


class SessionNotFound(RuntimeError):
    """Raised when no active session matches the request."""


class AudioSession:
    """A single recording session: capture → WAV tee + live stream queue.

    The capture callback runs on a PortAudio thread; the stream queue lives
    on the asyncio event loop. Blocks cross that boundary via
    ``loop.call_soon_threadsafe`` — never touch an asyncio.Queue directly
    from a foreign thread.
    """

    def __init__(
        self,
        source: AudioSource,
        loop: asyncio.AbstractEventLoop,
        vad_enabled: bool = True,
    ) -> None:
        """Create the session and its capture; does not start streaming yet.

        Raises:
            RuntimeError: If the required audio device cannot be found.
        """
        self.session_id = uuid.uuid4().hex[:12]
        self.source: AudioSource = source
        self.started_at = datetime.now()
        self._loop = loop
        self.stream_queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue(
            maxsize=STREAM_QUEUE_MAXSIZE
        )
        self._stream_drops = 0

        # Voice-activity segmentation runs on the lossless audio thread so it
        # sees every block; it drives the live "speaking" dot and feeds the
        # transcriber worker.
        self.vad_enabled = vad_enabled
        self._segmenter: SpeechSegmenter | None = (
            SpeechSegmenter(SileroVAD()) if vad_enabled else None
        )
        self._speech_active = False

        # Speech segments cross from the audio thread to the transcriber
        # worker via _seg_queue; finished transcripts fan out to the
        # transcription WebSocket via transcript_queue.
        self._seg_queue: asyncio.Queue[tuple[SpeechSegment, float] | None] = (
            asyncio.Queue()
        )
        self.transcript_queue: asyncio.Queue[TranscriptSegment | None] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

        # Set by the manager once the meeting row exists; the worker persists
        # each transcript against it.
        self.meeting_id: int | None = None

        wav_name = f"{self.started_at:%Y-%m-%d_%H%M%S}_{self.session_id}.wav"
        self.recorder = SessionRecorder(default_recordings_dir() / wav_name)

        if source == "both":
            self.capture: MixedAudioCapture | MicrophoneCapture | SystemAudioCapture = (
                MixedAudioCapture(callback=self._on_block)
            )
        elif source == "mic":
            self.capture = MicrophoneCapture(
                device=MicrophoneCapture.find_device(), callback=self._on_block
            )
        else:
            self.capture = SystemAudioCapture(
                device=SystemAudioCapture.find_device(), callback=self._on_block
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _on_block(self, block: np.ndarray) -> None:
        """Audio-thread callback: tee to disk, run VAD, then stream."""
        self.recorder.write(block)
        if self._segmenter is not None:
            for segment in self._segmenter.process(block):
                self._loop.call_soon_threadsafe(
                    self._seg_queue.put_nowait, (segment, time.monotonic())
                )
            self._speech_active = self._segmenter.is_speech_active
        self._loop.call_soon_threadsafe(self._enqueue_for_stream, block)

    def _enqueue_for_stream(self, block: np.ndarray) -> None:
        """Runs on the event loop; drops the block if the consumer lags."""
        try:
            self.stream_queue.put_nowait(block)
        except asyncio.QueueFull:
            self._stream_drops += 1
            if self._stream_drops == 1:
                logger.warning(
                    "Stream queue full — dropping WebSocket audio "
                    "(recording on disk is unaffected)."
                )

    def _end_stream(self) -> None:
        """Deliver the end-of-stream sentinel, evicting a block if full."""
        if self.stream_queue.full():
            self.stream_queue.get_nowait()
        self.stream_queue.put_nowait(None)

    async def _transcribe_worker(self) -> None:
        """Drain speech segments → Whisper → transcript_queue (event loop task).

        Whisper runs in a worker thread so neither the model load nor
        inference blocks the event loop. Per-stage latencies are logged for
        the Day 15 performance pass.
        """
        transcriber = await asyncio.to_thread(get_transcriber)
        while True:
            item = await self._seg_queue.get()
            if item is None:
                break
            segment, enqueued_at = item
            wait_ms = (time.monotonic() - enqueued_at) * 1000
            t0 = time.monotonic()
            transcript = await asyncio.to_thread(
                transcriber.transcribe, segment.audio, segment.start_ms
            )
            asr_ms = (time.monotonic() - t0) * 1000
            if transcript is not None:
                logger.info(
                    "Transcript [seg %dms · wait %.0fms · asr %.0fms]: %s",
                    segment.duration_ms,
                    wait_ms,
                    asr_ms,
                    transcript.text,
                )
                if self.meeting_id is not None:
                    insert_segment(
                        get_db(),
                        self.meeting_id,
                        text=transcript.text,
                        start_ms=transcript.start_ms,
                        end_ms=transcript.end_ms,
                        language=transcript.language,
                        confidence=transcript.confidence,
                    )
                await self.transcript_queue.put(transcript)
        await self.transcript_queue.put(None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def system_available(self) -> bool:
        """True if system audio is actually part of this session."""
        if isinstance(self.capture, MixedAudioCapture):
            return self.capture.system_available
        return isinstance(self.capture, SystemAudioCapture)

    @property
    def speech_active(self) -> bool:
        """True while the VAD segmenter has speech in progress.

        Written on the audio thread and read on the event loop; a lone bool
        read/write needs no lock under CPython.
        """
        return self._speech_active

    def start(self) -> None:
        """Start recorder and capture; on capture failure, leave no debris."""
        self.recorder.start()
        try:
            self.capture.start()
        except Exception:
            self.recorder.close()
            self.recorder.path.unlink(missing_ok=True)
            raise
        if self._segmenter is not None:
            self._worker_task = self._loop.create_task(self._transcribe_worker())
        logger.info(
            "Session %s started (source=%s) → %s",
            self.session_id,
            self.source,
            self.recorder.path,
        )

    def stop(self) -> None:
        """Stop capture, flush the WAV, end the stream. Blocking — call
        via ``asyncio.to_thread`` from async code."""
        self.capture.stop()
        self.recorder.close()
        if self._segmenter is not None:
            tail = self._segmenter.flush()
            if tail is not None:
                self._loop.call_soon_threadsafe(
                    self._seg_queue.put_nowait, (tail, time.monotonic())
                )
            self._loop.call_soon_threadsafe(self._seg_queue.put_nowait, None)
        self._loop.call_soon_threadsafe(self._end_stream)
        logger.info(
            "Session %s stopped (%.1f s recorded).",
            self.session_id,
            self.recorder.duration_seconds,
        )


class SessionManager:
    """Registry enforcing the one-active-session rule."""

    def __init__(self) -> None:
        self._active: AudioSession | None = None

    @property
    def active(self) -> AudioSession | None:
        """The currently running session, if any."""
        return self._active

    def start(self, source: AudioSource, vad_enabled: bool = True) -> AudioSession:
        """Create and start a session.

        Raises:
            SessionConflict: If a session is already active.
            RuntimeError: If the required audio device is missing.
        """
        if self._active is not None:
            raise SessionConflict(
                f"Session {self._active.session_id} is already active. "
                "Stop it before starting a new one."
            )
        session = AudioSession(
            source, asyncio.get_running_loop(), vad_enabled=vad_enabled
        )
        # Create the meeting row before starting the worker, so it has an id
        # to persist segments against from its very first transcript.
        session.meeting_id = create_meeting(
            get_db(),
            source=source,
            wav_path=str(session.recorder.path),
            started_at=session.started_at,
        )
        session.start()
        self._active = session
        return session

    async def stop(self) -> AudioSession:
        """Stop the active session and return it for a final summary.

        Raises:
            SessionNotFound: If no session is active.
        """
        if self._active is None:
            raise SessionNotFound("No active session to stop.")
        session, self._active = self._active, None
        await asyncio.to_thread(session.stop)
        # Wait for the worker to drain (incl. the flushed final segment) so
        # everything is persisted before the meeting is marked ready.
        if session._worker_task is not None:
            try:
                await asyncio.wait_for(session._worker_task, timeout=30)
            except (TimeoutError, asyncio.CancelledError):
                session._worker_task.cancel()
        if session.meeting_id is not None:
            # Mark processing, then diarize in the background → ready.
            end_meeting(
                get_db(),
                session.meeting_id,
                ended_at=datetime.now(),
                status="processing",
            )
            diarization_job.schedule(
                session.meeting_id, str(session.recorder.path)
            )
        return session

    def get(self, session_id: str) -> AudioSession:
        """Return the active session matching ``session_id``.

        Raises:
            SessionNotFound: If it does not match the active session.
        """
        if self._active is None or self._active.session_id != session_id:
            raise SessionNotFound(f"No active session with id {session_id!r}.")
        return self._active


#: Process-wide registry — the app has exactly one.
manager = SessionManager()
