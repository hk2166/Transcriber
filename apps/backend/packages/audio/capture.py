from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

__all__ = ["AudioCapture", "MicrophoneCapture", "SystemAudioCapture"]


class AudioCapture:
    """Base class for audio capture devices.

    Handles stream lifecycle, thread safety, and the sounddevice callback
    plumbing. Subclasses specialise device discovery and any device-specific
    configuration.

    Audio format (shared by all subclasses unless overridden):
        Sample rate:  16 000 Hz
        Channels:     1 (Mono)
        Data type:    float32
        Block size:   1 024 samples (~64 ms latency)
    """

    SAMPLE_RATE: int = 16_000
    CHANNELS: int = 1
    BLOCKSIZE: int = 1_024
    DTYPE: str = "float32"

    def __init__(
        self,
        device: int | str,
        callback: Callable[[np.ndarray], None],
    ) -> None:
        """Initialise an audio capture instance.

        Args:
            device: Device index (int) or name substring (str) as recognised
                by sounddevice / PortAudio.
            callback: Called on every audio block with a *copy* of the block
                as a ``(BLOCKSIZE, CHANNELS)`` float32 ndarray.

        Raises:
            ValueError: If ``device`` is ``None`` (runtime guard for
                callers that bypass type checking).
        """
        if device is None:
            raise ValueError("Audio device cannot be None.")
        self.device = device
        self.callback = callback
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        """sounddevice stream callback — executed on a dedicated audio thread.

        Args:
            indata: Raw audio block. This is a shared PortAudio buffer;
                it must be copied before being stored or passed elsewhere.
            frames: Number of frames in this block (always equals BLOCKSIZE).
            time_info: PortAudio timing struct (cffi CData); available for
                latency measurement but rarely needed.
            status: Non-zero flags indicate an input overflow or other issue.
        """
        if status:
            logger.warning("Audio stream status: %s", status)
        self.callback(indata.copy())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True if the audio stream is currently active."""
        with self._lock:
            return self._stream is not None

    def start(self) -> None:
        """Open and start the audio stream.

        Raises:
            RuntimeError: If the stream is already running.
        """
        with self._lock:
            if self._stream is not None:
                raise RuntimeError(
                    f"{self.__class__.__name__} stream is already running."
                )
            stream = sd.InputStream(
                device=self.device,
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                blocksize=self.BLOCKSIZE,
                callback=self._audio_callback,
            )
            stream.start()
            self._stream = stream

        logger.info(
            "%s started (device=%r, sample_rate=%d, channels=%d)",
            self.__class__.__name__,
            self.device,
            self.SAMPLE_RATE,
            self.CHANNELS,
        )

    def stop(self) -> None:
        """Stop and close the audio stream.

        Safe to call when the stream is not running (logs a debug message
        and returns). The lock is released before blocking on stream.stop()
        so that callbacks already in-flight can complete without deadlock.
        """
        with self._lock:
            if self._stream is None:
                logger.debug(
                    "%s.stop() called but stream is not running.",
                    self.__class__.__name__,
                )
                return
            # Take ownership; release the lock before the blocking stop() call.
            stream, self._stream = self._stream, None

        stream.stop()
        stream.close()
        logger.info("%s stopped.", self.__class__.__name__)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> AudioCapture:
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()


class SystemAudioCapture(AudioCapture):
    """Captures system audio via the BlackHole 2ch virtual loopback device.

    Use :meth:`find_device` to resolve the BlackHole device index, then
    pass it to the constructor.

    Audio format: 16 kHz · Mono · float32 · 1 024-sample blocks.
    """

    @staticmethod
    def find_device() -> int:
        """Return the device index of the first BlackHole input device.

        Returns:
            Integer device index suitable for passing to the constructor.

        Raises:
            RuntimeError: If no BlackHole input device is found. Ensure
                BlackHole 2ch is installed and listed in Audio MIDI Setup.
        """
        for index, device in enumerate(sd.query_devices()):
            if "BlackHole" in device["name"] and device["max_input_channels"] > 0:
                logger.debug(
                    "Found BlackHole device #%d: %s", index, device["name"]
                )
                return index
        raise RuntimeError(
            "BlackHole 2ch device not found. "
            "Install BlackHole and configure it as a loopback input."
        )


class MicrophoneCapture(AudioCapture):
    """Captures audio from the default system microphone.

    Use :meth:`find_device` to resolve the preferred microphone device index,
    then pass it to the constructor.

    Audio format: 16 kHz · Mono · float32 · 1 024-sample blocks.
    """

    @staticmethod
    def find_device() -> int:
        """Return the device index of the preferred microphone.

        Tries the system default input device first, then falls back to the
        first available input device.

        Returns:
            Integer device index suitable for passing to the constructor.

        Raises:
            RuntimeError: If no input device is found.
        """
        devices = sd.query_devices()
        default_index: int = sd.default.device[0]  # type: ignore[index]

        if default_index is not None and default_index >= 0:
            device = devices[default_index]
            if device["max_input_channels"] > 0:
                logger.debug(
                    "Using default microphone #%d: %s",
                    default_index,
                    device["name"],
                )
                return default_index

        for index, device in enumerate(devices):
            if device["max_input_channels"] > 0:
                logger.debug(
                    "Falling back to microphone #%d: %s", index, device["name"]
                )
                return index

        raise RuntimeError("No microphone input device found.")