"""Speaker diarization (pyannote) — post-meeting only, never on the live path.

torch-heavy and slow (RTF ~0.3 on CPU), so it runs in the background after a
meeting ends. torch/pyannote are imported lazily inside methods, so importing
this module stays torch-free — only constructing a :class:`SpeakerDiarizer`
loads them.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

__all__ = ["SpeakerDiarizer", "SpeakerTurn"]


@dataclass
class SpeakerTurn:
    """A span attributed to one speaker (label like ``"SPEAKER_00"``)."""

    speaker: str
    start_ms: int
    end_ms: int


class SpeakerDiarizer:
    """Wraps ``pyannote/speaker-diarization-3.1``, loaded once and reused.

    Audio is passed as a **waveform tensor**, not a file path: pyannote 4.x
    decodes files via torchcodec, which needs ffmpeg dylibs that aren't
    reliably present. We already hold the WAV, so we decode it with soundfile
    and hand pyannote the samples directly.
    """

    MODEL = "pyannote/speaker-diarization-3.1"
    SAMPLE_RATE = 16_000

    def __init__(self) -> None:
        # Force cache-only so a shipped app never phones Hugging Face.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from pyannote.audio import Pipeline

        self._pipeline = Pipeline.from_pretrained(self.MODEL)
        logger.info("SpeakerDiarizer loaded (%s).", self.MODEL)

    def diarize(
        self, audio: np.ndarray, sample_rate: int = SAMPLE_RATE
    ) -> list[SpeakerTurn]:
        """Diarize mono float32 audio; return speaker turns in time order."""
        import torch

        samples = np.ascontiguousarray(np.asarray(audio, dtype=np.float32).reshape(1, -1))
        output = self._pipeline(
            {"waveform": torch.from_numpy(samples), "sample_rate": sample_rate}
        )
        turns = [
            SpeakerTurn(
                speaker=label,
                start_ms=int(segment.start * 1000),
                end_ms=int(segment.end * 1000),
            )
            for segment, _, label in output.speaker_diarization.itertracks(
                yield_label=True
            )
        ]
        turns.sort(key=lambda turn: turn.start_ms)
        logger.info(
            "Diarized %d turns across %d speakers.",
            len(turns),
            len({turn.speaker for turn in turns}),
        )
        return turns

    def diarize_file(self, path: str) -> list[SpeakerTurn]:
        """Diarize a WAV file (loaded with soundfile, not torchcodec)."""
        import soundfile as sf

        audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
        return self.diarize(audio[:, 0], sample_rate)
