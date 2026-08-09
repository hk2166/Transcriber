"""In-memory audio session management.

One active session at a time (v1). A session owns the capture pipeline:
capture → recorder tee (always, lossless) + bounded stream queue (WebSocket).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Literal

import numpy as np

from packages.audio import (
    MicrophoneCapture,
    MixedAudioCapture,
    SessionRecorder,
    SystemAudioCapture,
    default_recordings_dir,
)

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

    def __init__(self, source: AudioSource, loop: asyncio.AbstractEventLoop) -> None:
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
        """Audio-thread callback: tee to disk first, then to the stream."""
        self.recorder.write(block)
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def system_available(self) -> bool:
        """True if system audio is actually part of this session."""
        if isinstance(self.capture, MixedAudioCapture):
            return self.capture.system_available
        return isinstance(self.capture, SystemAudioCapture)

    def start(self) -> None:
        """Start recorder and capture; on capture failure, leave no debris."""
        self.recorder.start()
        try:
            self.capture.start()
        except Exception:
            self.recorder.close()
            self.recorder.path.unlink(missing_ok=True)
            raise
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

    def start(self, source: AudioSource) -> AudioSession:
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
        session = AudioSession(source, asyncio.get_running_loop())
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
