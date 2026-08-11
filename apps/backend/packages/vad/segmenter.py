"""Speech segmentation — turns a per-block VAD signal into speech segments.

The segmenter consumes audio blocks, asks a VAD for a speech probability per
block, and runs a small hysteresis state machine: it buffers audio while
speech is active and emits a :class:`SpeechSegment` once a long-enough silence
follows. Short blips are dropped (``min_speech_ms``) and brief pauses do not
split a segment (``min_silence_ms``), so Whisper only ever sees real speech.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

__all__ = ["SpeechSegment", "SpeechSegmenter"]


@dataclass
class SpeechSegment:
    """A contiguous span of speech extracted from the stream.

    Attributes:
        audio: 1-D float32 samples (16 kHz mono), including leading/trailing
            padding.
        start_ms: Segment start relative to stream start, in milliseconds.
        end_ms: Segment end relative to stream start, in milliseconds.
    """

    audio: np.ndarray
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        """Segment duration in milliseconds."""
        return self.end_ms - self.start_ms


class SpeechSegmenter:
    """Streaming speech/silence segmenter driven by a VAD.

    The ``vad`` dependency only needs a ``confidence(chunk) -> float`` method
    (and optionally ``reset()``); :class:`~packages.vad.silero.SileroVAD`
    satisfies it, and tests inject a scripted fake. Hysteresis uses two
    thresholds: a block counts as speech at or above ``threshold`` and as
    silence below ``neg_threshold``; values in between sustain the current
    state, which keeps segment boundaries from chattering.

    Feed blocks with :meth:`process` (returns any segments completed by that
    block — usually none, occasionally one). Call :meth:`flush` at end of
    stream to emit speech still in progress. :attr:`is_speech_active` drives a
    live "speaking" indicator.
    """

    def __init__(
        self,
        vad,
        threshold: float = 0.5,
        neg_threshold: float | None = None,
        min_speech_ms: int = 250,
        min_silence_ms: int = 700,
        padding_ms: int = 200,
        sample_rate: int = 16_000,
    ) -> None:
        """Configure the segmenter.

        Args:
            vad: Object with ``confidence(chunk) -> float`` (and optional
                ``reset()``).
            threshold: Probability at/above which a block is speech.
            neg_threshold: Probability below which a block is silence.
                Defaults to ``threshold - 0.15`` (floored at 0.01).
            min_speech_ms: Segments whose core speech is shorter are dropped.
            min_silence_ms: Silence this long ends a segment.
            padding_ms: Audio kept on each side of the speech core.
            sample_rate: Audio sample rate (Hz).
        """
        self.vad = vad
        self.threshold = threshold
        self.neg_threshold = (
            neg_threshold if neg_threshold is not None else max(threshold - 0.15, 0.01)
        )
        self.sample_rate = sample_rate
        self.min_speech_samples = int(min_speech_ms * sample_rate / 1000)
        self.min_silence_samples = int(min_silence_ms * sample_rate / 1000)
        self.padding_samples = int(padding_ms * sample_rate / 1000)
        self.reset()

    def reset(self) -> None:
        """Clear all state (and the VAD's) — call between recordings."""
        if hasattr(self.vad, "reset"):
            self.vad.reset()
        self._pos = 0
        self._triggered = False
        self._pre_buf: deque[np.ndarray] = deque()
        self._pre_samples = 0
        self._speech_buf: list[np.ndarray] = []
        self._seg_start = 0
        self._trigger_pos = 0
        self._silence_samples = 0

    @property
    def is_speech_active(self) -> bool:
        """True while a speech segment is in progress (drives the live dot)."""
        return self._triggered

    def _ms(self, sample: int) -> int:
        return round(sample * 1000 / self.sample_rate)

    def process(self, block: np.ndarray) -> list[SpeechSegment]:
        """Feed one audio block; return any segments it completed.

        Args:
            block: 1-D or ``(N, 1)`` float32 audio at ``sample_rate``.
        """
        x = np.asarray(block, dtype=np.float32).reshape(-1)
        n = x.size
        conf = self.vad.confidence(x)
        end_pos = self._pos + n
        out: list[SpeechSegment] = []

        if not self._triggered:
            # Keep a rolling pre-buffer so a segment can include leading
            # padding from just before speech onset. Never drop the last
            # block — it may be the one that triggers.
            self._pre_buf.append(x)
            self._pre_samples += n
            while (
                len(self._pre_buf) > 1
                and self._pre_samples - self._pre_buf[0].size >= self.padding_samples
            ):
                self._pre_samples -= self._pre_buf.popleft().size

            if conf >= self.threshold:
                self._triggered = True
                self._speech_buf = [np.concatenate(list(self._pre_buf))]
                self._seg_start = end_pos - self._pre_samples
                self._trigger_pos = self._pos
                self._silence_samples = 0
        else:
            self._speech_buf.append(x)
            if conf < self.neg_threshold:
                self._silence_samples += n
                if self._silence_samples >= self.min_silence_samples:
                    seg = self._finish(end_pos)
                    if seg is not None:
                        out.append(seg)
            else:
                self._silence_samples = 0

        self._pos = end_pos
        return out

    def _finish(self, end_pos: int) -> SpeechSegment | None:
        """Close the active segment, trimming trailing silence to padding."""
        silence_start = end_pos - self._silence_samples
        core = silence_start - self._trigger_pos
        seg_end = silence_start + self.padding_samples

        audio = np.concatenate(self._speech_buf)[: seg_end - self._seg_start]
        seg_start = self._seg_start

        self._triggered = False
        self._speech_buf = []
        self._pre_buf.clear()
        self._pre_samples = 0
        self._silence_samples = 0

        if core < self.min_speech_samples:
            return None
        return SpeechSegment(audio, self._ms(seg_start), self._ms(seg_end))

    def flush(self) -> SpeechSegment | None:
        """Emit speech still in progress at end of stream, if long enough."""
        if not self._triggered:
            return None
        end_pos = self._pos
        core = end_pos - self._trigger_pos
        audio = np.concatenate(self._speech_buf)
        seg_start = self._seg_start

        self._triggered = False
        self._speech_buf = []

        if core < self.min_speech_samples:
            return None
        return SpeechSegment(audio, self._ms(seg_start), self._ms(end_pos))
