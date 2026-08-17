from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from packages.transcription import WhisperTranscriber

FIXTURE = Path(__file__).parent / "fixtures" / "known_speech.wav"

@pytest.fixture(scope="module")
def transcriber() -> WhisperTranscriber:
    # Auto-detect (language=None) to match production and exercise the
    # low-confidence-language hallucination guard.
    return WhisperTranscriber(model_size="small")


def test_transcribes_known_keywords(transcriber):
    audio, _ = sf.read(FIXTURE, dtype="float32", always_2d=True)
    segment = transcriber.transcribe(audio[:, 0], start_ms=1000)

    assert segment is not None
    lowered = segment.text.lower()
    for keyword in ("quarterly", "budget", "tuesday"):
        assert keyword in lowered
    assert segment.language == "en"
    assert 0.0 < segment.confidence <= 1.0
    assert segment.start_ms >= 1000


def test_silence_returns_none(transcriber):
    assert transcriber.transcribe(np.zeros(16000, dtype="float32")) is None


def test_low_noise_does_not_hallucinate(transcriber):
    # Faint broadband noise the VAD might let through must not become text
    # (Whisper would otherwise invent a phrase in a random language).
    rng = np.random.RandomState(0)
    noise = (0.01 * rng.randn(16000 * 3)).astype("float32")
    assert transcriber.transcribe(noise) is None
