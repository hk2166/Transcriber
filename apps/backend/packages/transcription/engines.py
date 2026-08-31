"""The transcription-engine catalog + factory.

One place that maps an engine id (e.g. ``"whisper-small"``, ``"parakeet-v3"``)
to a live transcriber, and describes the choices for the Settings UI.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ASR_ENGINES", "DEFAULT_ENGINE", "make_transcriber"]

DEFAULT_ENGINE = "whisper-small"


@dataclass(frozen=True)
class EngineSpec:
    id: str
    label: str
    note: str
    languages: str
    size_mb: int
    family: str  # "whisper" | "parakeet"


ASR_ENGINES: list[EngineSpec] = [
    EngineSpec("whisper-base", "Whisper · Base", "Fastest, lowest accuracy", "99", 150, "whisper"),
    EngineSpec("whisper-small", "Whisper · Small (default)", "Balanced speed and accuracy", "99", 480, "whisper"),
    EngineSpec("whisper-medium", "Whisper · Medium", "Higher accuracy, slower", "99", 1500, "whisper"),
    EngineSpec("parakeet-v2", "Parakeet · English", "Best English accuracy — NVIDIA, beats Whisper-large", "English", 650, "parakeet"),
    EngineSpec("parakeet-v3", "Parakeet · Multilingual", "Top accuracy across 25 languages", "25", 680, "parakeet"),
]

ENGINES_BY_ID = {spec.id: spec for spec in ASR_ENGINES}


def make_transcriber(engine: str):
    """Build the transcriber for an engine id (defaults to Whisper-small)."""
    if engine.startswith("parakeet"):
        from packages.transcription.parakeet import ParakeetTranscriber

        return ParakeetTranscriber(variant=engine)
    from packages.transcription.transcriber import WhisperTranscriber

    size = engine.split("-", 1)[1] if engine.startswith("whisper-") else "small"
    return WhisperTranscriber(model_size=size)
