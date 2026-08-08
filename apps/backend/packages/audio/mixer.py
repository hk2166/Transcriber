"""Mixed microphone + system audio capture for MeetingMind."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from typing import Any

import numpy as np

from packages.audio.capture import AudioCapture, MicrophoneCapture, SystemAudioCapture

logger = logging.getLogger(__name__)

__all__ = ["MixedAudioCapture"]


class MixedAudioCapture:
    """Merges microphone and system (BlackHole) audio into one mono stream.

    Composition over inheritance: owns a :class:`MicrophoneCapture` and,
    when BlackHole is installed, a :class:`SystemAudioCapture`, while
    exposing the same ``start``/``stop``/context-manager surface as
    :class:`AudioCapture`.

    The microphone is the timing master. Every mic block is summed with
    the oldest buffered system block — or with silence when none is
    buffered — and delivered to ``callback`` in the exact format of the
    child streams (16 kHz · mono · float32 · 1 024-sample blocks), so
    consumers cannot tell mixed audio from single-source audio.

    Clock drift between the two devices is absorbed by a bounded FIFO:
    a system device running ahead of the mic drops its oldest audio; one
    running behind gets silence mixed in for that block.

    When no BlackHole device exists, construction succeeds in mic-only
    mode and :attr:`system_available` is ``False``.
    """

    SAMPLE_RATE: int = AudioCapture.SAMPLE_RATE
    CHANNELS: int = AudioCapture.CHANNELS
    BLOCKSIZE: int = AudioCapture.BLOCKSIZE

    #: System blocks buffered before the oldest is dropped (32 ≈ 2 s).
    MAX_BUFFERED_BLOCKS: int = 32

    def __init__(
        self,
        callback: Callable[[np.ndarray], None],
        mic_gain: float = 1.0,
        system_gain: float = 1.0,
    ) -> None:
        """Initialise the mixed capture.

        Args:
            callback: Called on every mixed block with a
                ``(BLOCKSIZE, CHANNELS)`` float32 ndarray.
            mic_gain: Linear gain applied to microphone audio before summing.
            system_gain: Linear gain applied to system audio before summing.
                The mixed sum is clipped to [-1.0, 1.0].
        """
        self.callback = callback
        self.mic_gain = mic_gain
        self.system_gain = system_gain

        self._system_blocks: deque[np.ndarray] = deque(maxlen=self.MAX_BUFFERED_BLOCKS)
        self._overflow_logged = False

        self._mic = MicrophoneCapture(
            device=MicrophoneCapture.find_device(),
            callback=self._on_mic_block,
        )

        self._system: SystemAudioCapture | None = None
        try:
            self._system = SystemAudioCapture(
                device=SystemAudioCapture.find_device(),
                callback=self._on_system_block,
            )
        except RuntimeError as exc:
            logger.warning("System audio unavailable — running mic-only: %s", exc)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _on_system_block(self, block: np.ndarray) -> None:
        """Buffer a system block (runs on the system-audio thread)."""
        if (
            len(self._system_blocks) == self.MAX_BUFFERED_BLOCKS
            and not self._overflow_logged
        ):
            logger.warning(
                "System audio buffer full (%d blocks) — dropping oldest audio; "
                "the system device is running ahead of the microphone.",
                self.MAX_BUFFERED_BLOCKS,
            )
            self._overflow_logged = True
        self._system_blocks.append(block)

    def _on_mic_block(self, block: np.ndarray) -> None:
        """Mix a mic block with buffered system audio (mic-audio thread)."""
        try:
            system: np.ndarray | None = self._system_blocks.popleft()
        except IndexError:
            system = None

        mixed = block * self.mic_gain
        if system is not None:
            mixed += system * self.system_gain
        np.clip(mixed, -1.0, 1.0, out=mixed)
        self.callback(mixed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def system_available(self) -> bool:
        """True if a BlackHole device was found at construction time."""
        return self._system is not None

    @property
    def is_running(self) -> bool:
        """True if the capture is currently active."""
        return self._mic.is_running

    def start(self) -> None:
        """Start the child streams (system first, so its buffer is primed).

        Raises:
            RuntimeError: If the capture is already running.
        """
        if self._system is not None:
            self._system.start()
        try:
            self._mic.start()
        except Exception:
            if self._system is not None:
                self._system.stop()
            raise
        logger.info(
            "MixedAudioCapture started (system_audio=%s).",
            "on" if self._system is not None else "off",
        )

    def stop(self) -> None:
        """Stop both child streams and clear the drift buffer."""
        self._mic.stop()
        if self._system is not None:
            self._system.stop()
        self._system_blocks.clear()
        self._overflow_logged = False
        logger.info("MixedAudioCapture stopped.")

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> MixedAudioCapture:
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()