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

import postprocess_job
from database import get_db
from packages.audio import (
    MicrophoneCapture,
    MixedAudioCapture,
    SessionRecorder,
    SystemAudioCapture,
    default_recordings_dir,
)
from packages.storage import create_meeting, end_meeting, insert_segment
from packages.transcription import TranscriptSegment, make_transcriber
from packages.vad import SileroVAD, SpeechSegment, SpeechSegmenter
from settings import get_settings

logger = logging.getLogger(__name__)

__all__ = [
    "AudioSession",
    "AudioSource",
    "SessionConflict",
    "SessionNotFound",
    "manager",
]

AudioSource = Literal["mic", "system", "both", "import"]

#: Stream buffer: 256 blocks ≈ 16 s of audio. Overflow drops WebSocket
#: audio only — the recorder tee always receives every block.
STREAM_QUEUE_MAXSIZE = 256
#: Speech-segment backlog for the live transcriber. Each item carries its
#: audio, so this must be bounded: if the engine falls behind, we drop live
#: speech (and say so once) rather than let audio pile up in memory — the WAV
#: on disk is lossless and the post-meeting refine recovers the text.
SEG_QUEUE_MAXSIZE = 64

_transcriber = None
_transcriber_lock = threading.Lock()


def get_transcriber():
    """
    Return the process-wide transcriber, loading it once on first use.

    Uses the configured engine (Whisper or Parakeet). Switching engines calls
    :func:`reset_transcriber`, so the new engine loads on the next recording —
    no process restart needed. Blocking — call from a worker thread.
    """
    global _transcriber
    with _transcriber_lock:
        if _transcriber is None:
            _transcriber = make_transcriber(get_settings().transcription_engine)
        return _transcriber


def reset_transcriber() -> None:
    """Drop the cached transcriber so the next recording reloads the configured
    engine. Safe mid-session: an active worker keeps its own reference; only the
    *next* ``get_transcriber`` is affected."""
    global _transcriber
    with _transcriber_lock:
        _transcriber = None
    


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
        threshold = get_settings().vad_threshold
        self._segmenter: SpeechSegmenter | None = (
            SpeechSegmenter(SileroVAD(threshold=threshold), threshold=threshold)
            if vad_enabled
            else None
        )
        self._speech_active = False

        # Pause gates the whole _on_block path at once: recorder, VAD, and
        # stream all freeze together, so the segmenter's sample clock stays
        # aligned with the WAV file (timestamps are sample-count time).
        # Written on the event loop, read on the audio thread — same lone-bool
        # pattern as _speech_active.
        self._paused = False

        # Speech segments cross from the audio thread to the transcriber
        # worker via _seg_queue; finished transcripts fan out to the
        # transcription WebSocket via transcript_queue.
        self._seg_queue: asyncio.Queue[tuple[SpeechSegment, float] | None] = (
            asyncio.Queue(maxsize=SEG_QUEUE_MAXSIZE)
        )
        self._seg_drops = 0
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
        if self._paused:
            return
        self.recorder.write(block)
        if self._segmenter is not None:
            for segment in self._segmenter.process(block):
                self._loop.call_soon_threadsafe(
                    self._enqueue_segment, (segment, time.monotonic())
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

    def _enqueue_segment(self, item: tuple[SpeechSegment, float]) -> None:
        """Runs on the event loop; drops speech if the transcriber is far
        behind rather than growing the queue without bound."""
        try:
            self._seg_queue.put_nowait(item)
        except asyncio.QueueFull:
            self._seg_drops += 1
            if self._seg_drops == 1:
                logger.warning(
                    "Transcriber can't keep up — dropping live speech segments "
                    "(the recording on disk is unaffected; refine recovers it)."
                )

    def _end_segments(self) -> None:
        """Deliver the worker's end sentinel, evicting a segment if full."""
        if self._seg_queue.full():
            self._seg_queue.get_nowait()
        self._seg_queue.put_nowait(None)

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

    @property
    def paused(self) -> bool:
        """True while the session is paused (capture running, blocks dropped)."""
        return self._paused

    def pause(self) -> None:
        """Freeze the pipeline without tearing anything down.

        The capture devices keep running (no re-open race on resume); blocks
        are simply dropped at the top of ``_on_block``. Mid-speech buffers in
        the segmenter stay put — on resume the segment continues, which
        matches the gapless WAV exactly.
        """
        self._paused = True
        self._speech_active = False
        logger.info("Session %s paused.", self.session_id)

    def resume(self) -> None:
        """Un-freeze the pipeline; audio flows again on the next block."""
        self._paused = False
        logger.info("Session %s resumed.", self.session_id)

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
                    self._enqueue_segment, (tail, time.monotonic())
                )
            self._loop.call_soon_threadsafe(self._end_segments)
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
            postprocess_job.schedule(
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

    def finalize_for_shutdown(self) -> None:
        """Fast, best-effort finalize of the active session when the app is
        quitting (Cmd-Q → SIGTERM).

        Flushes the WAV header and marks the meeting ``processing`` so the next
        launch's reconciliation completes it — deliberately WITHOUT the 30 s
        worker drain (the host escalates to SIGKILL shortly after SIGTERM) or
        scheduling post-processing (the event loop is closing). Quitting instead
        of pressing Stop must never strand a recording; boot reconciliation then
        turns this ``processing`` row into a finished meeting.
        """
        session, self._active = self._active, None
        if session is None:
            return
        try:
            session.stop()  # stops capture + closes the WAV (valid header)
        except Exception:
            logger.exception(
                "Error stopping session %s on shutdown.", session.session_id
            )
        if session.meeting_id is not None:
            end_meeting(
                get_db(),
                session.meeting_id,
                ended_at=datetime.now(),
                status="processing",
            )
        logger.info(
            "Finalized session %s for shutdown → processing.", session.session_id
        )


#: Process-wide registry — the app has exactly one.
manager = SessionManager()
