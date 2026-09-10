"""Session recording — tees captured audio blocks to a WAV file on disk."""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from packages.audio.capture import AudioCapture

logger = logging.getLogger(__name__)

__all__ = ["SessionRecorder", "default_recordings_dir"]

#: Single source of truth for the app-data folder name.
APP_DIR_NAME = "Confab"

#: Pre-rename (Day 16) folder name; migrated on first launch.
_LEGACY_DIR_NAME = "MeetingMind"


def default_recordings_dir() -> Path:
    """Return the macOS recordings directory, creating it if needed."""
    app_support = Path.home() / "Library" / "Application Support"
    app_dir = app_support / APP_DIR_NAME
    legacy = app_support / _LEGACY_DIR_NAME
    if legacy.is_dir() and not app_dir.exists():
        legacy.rename(app_dir)
        logger.info("Migrated app data: %s -> %s", legacy, app_dir)
    path = app_dir / "recordings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def decode_to_wav(src_path: str, dst_path: str, sample_rate: int = 16000) -> float:
    """Decode any PyAV-readable audio/video file to 16 kHz mono PCM-16 WAV.

    Reuses faster-whisper's bundled PyAV decoder (the same one transcription
    uses), so mp3/m4a/aac/ogg and the audio track of mp4/mov all work with no
    new dependency. The result is exactly the WAV shape the transcriber,
    diarizer, and audio playback already expect. Raises on a file with no
    decodable audio. Returns the clip duration in seconds.
    """
    import soundfile as sf
    from faster_whisper.audio import decode_audio  # heavy import — keep it local

    audio = decode_audio(src_path, sampling_rate=sample_rate)  # mono float32 [-1, 1]
    if audio is None or len(audio) == 0:
        raise ValueError("No decodable audio in the file.")
    sf.write(dst_path, audio, sample_rate, subtype="PCM_16")
    return len(audio) / sample_rate


class SessionRecorder:
    """Writes audio blocks to a 16-bit PCM WAV file without blocking the caller.

    Built to sit inside an audio callback chain: :meth:`write` only enqueues
    the block and returns immediately; a dedicated writer thread drains the
    queue and performs all disk I/O. The queue is unbounded, which is safe
    because audio arrives at ~64 KB/s — far below disk throughput.

    Shutdown is loss-free: :meth:`close` enqueues a sentinel behind any
    pending blocks, so the writer flushes the full tail before exiting.
    Blocks written after :meth:`close` are dropped silently — raising inside
    a sounddevice callback would only produce stream-error noise.

    Audio format: 16 kHz · mono · 16-bit PCM WAV (converted from the float32
    blocks produced by the capture classes). ``path`` must end in ``.wav``.
    """

    SAMPLE_RATE: int = AudioCapture.SAMPLE_RATE
    CHANNELS: int = AudioCapture.CHANNELS

    _SENTINEL = None

    def __init__(self, path: Path | str) -> None:
        """Initialise the recorder without opening the file yet.

        Args:
            path: Target WAV path. Parent directories are created on
                :meth:`start`.
        """
        self.path = Path(path)
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._closed = False
        self._frames_written = 0
        self._thread: threading.Thread | None = None
        self._file: sf.SoundFile | None = None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        """Drain queued blocks to disk (runs on the writer thread)."""
        assert self._file is not None
        try:
            while True:
                block = self._queue.get()
                if block is self._SENTINEL:
                    return
                self._file.write(block)
                self._frames_written += len(block)
        except Exception:
            logger.exception(
                "SessionRecorder writer failed — recording truncated: %s", self.path
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """True between :meth:`start` and :meth:`close`."""
        return self._thread is not None and not self._closed

    @property
    def frames_written(self) -> int:
        """Number of audio frames flushed to disk so far."""
        return self._frames_written

    @property
    def duration_seconds(self) -> float:
        """Duration of the audio flushed to disk so far."""
        return self._frames_written / self.SAMPLE_RATE

    def start(self) -> None:
        """Open the WAV file and start the writer thread.

        Raises:
            RuntimeError: If the recorder was already started.
        """
        if self._thread is not None:
            raise RuntimeError("SessionRecorder is already started.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = sf.SoundFile(
            self.path,
            mode="w",
            samplerate=self.SAMPLE_RATE,
            channels=self.CHANNELS,
            subtype="PCM_16",
        )
        self._thread = threading.Thread(
            target=self._writer_loop, name="session-recorder", daemon=True
        )
        self._thread.start()
        logger.info("SessionRecorder started: %s", self.path)

    def write(self, block: np.ndarray) -> None:
        """Enqueue a block for writing. Never blocks, never raises.

        Args:
            block: ``(frames, CHANNELS)`` float32 ndarray in [-1.0, 1.0].
        """
        if self._closed:
            logger.debug("SessionRecorder.write() after close — block dropped.")
            return
        self._queue.put(block)

    def close(self) -> None:
        """Flush all pending blocks, stop the writer thread, close the file.

        Idempotent, and safe to call on a recorder that was never started.
        """
        if self._closed:
            return
        self._closed = True
        if self._thread is None:
            return
        self._queue.put(self._SENTINEL)
        self._thread.join()
        if self._file is not None:
            self._file.close()
        logger.info(
            "SessionRecorder closed: %s (%d frames, %.1f s)",
            self.path,
            self._frames_written,
            self.duration_seconds,
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> SessionRecorder:
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
