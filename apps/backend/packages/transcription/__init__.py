"""Speech-to-text for Confab: Whisper (faster-whisper) or NVIDIA Parakeet."""

from packages.transcription.engines import (
    ASR_ENGINES,
    DEFAULT_ENGINE,
    make_transcriber,
)
from packages.transcription.parakeet import PARAKEET_MODELS, ParakeetTranscriber
from packages.transcription.transcriber import TranscriptSegment, WhisperTranscriber

__all__ = [
    "ASR_ENGINES",
    "DEFAULT_ENGINE",
    "PARAKEET_MODELS",
    "ParakeetTranscriber",
    "TranscriptSegment",
    "WhisperTranscriber",
    "make_transcriber",
]
