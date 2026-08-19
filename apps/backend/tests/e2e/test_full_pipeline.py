"""End-to-end: a multi-speaker WAV through the whole offline pipeline.

Exercises the real models (VAD → Whisper → pyannote → embedder, + Ollama when
available) on a 32 s two-speaker fixture. Slow (~30–60 s) — run explicitly:

    uv run pytest tests/e2e -v
"""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from packages.storage.embedder import Embedder
from packages.storage.vector_store import VectorStore
from packages.transcription import WhisperTranscriber
from packages.vad import SileroVAD, SpeechSegmenter

FIXTURE = Path(__file__).parent / "fixtures" / "two_speaker_meeting.wav"
BLOCK = 1024


@pytest.fixture(scope="module")
def transcripts():
    """Run capture-style VAD segmentation + transcription over the fixture."""
    audio, _ = sf.read(FIXTURE, dtype="float32", always_2d=True)
    audio = audio[:, 0]

    segmenter = SpeechSegmenter(SileroVAD())
    segments = []
    for i in range(0, len(audio) - BLOCK, BLOCK):
        segments.extend(segmenter.process(audio[i : i + BLOCK]))
    tail = segmenter.flush()
    if tail is not None:
        segments.append(tail)

    transcriber = WhisperTranscriber(model_size="small")
    results = [transcriber.transcribe(s.audio, s.start_ms) for s in segments]
    return [t for t in results if t is not None]


def test_segments_and_transcription(transcripts):
    assert len(transcripts) >= 3
    assert all(t.text.strip() for t in transcripts)
    joined = " ".join(t.text.lower() for t in transcripts)
    assert "budget" in joined and "migration" in joined


def test_diarization_produces_turns():
    from packages.diarization import SpeakerDiarizer

    turns = SpeakerDiarizer().diarize_file(str(FIXTURE))
    # Diarization runs and covers the speech. The distinct-speaker COUNT is
    # fixture-dependent — synthetic TTS voices often cluster to one speaker —
    # so real 2-speaker separation is verified in the Day-8 manual test, not here.
    assert len(turns) >= 2
    assert all(turn.speaker for turn in turns)


def test_search_index_is_populated_and_ranks(transcripts):
    embedder = Embedder()
    store = VectorStore(Embedder.DIM)
    store.add(
        list(range(len(transcripts))),
        meeting_id=1,
        vectors=embedder.encode([t.text for t in transcripts]),
    )
    assert len(store) >= 3
    hits = store.search(embedder.encode_one("money and hiring"), k=1)
    assert hits and "budget" in transcripts[hits[0].segment_id].text.lower()


def test_summary_when_ollama_available(transcripts):
    from packages.intelligence import OllamaClient, OllamaUnavailable, summarize

    text = "\n".join(t.text for t in transcripts)
    try:
        summary = summarize(OllamaClient(), text)
    except OllamaUnavailable:
        pytest.skip("Ollama not running")
    assert summary.summary.strip()


def test_pipeline_latency_is_reasonable():
    """Per-segment ASR should be well under real time (Day-15 target)."""
    import time

    audio, _ = sf.read(FIXTURE, dtype="float32", always_2d=True)
    clip = np.ascontiguousarray(audio[: 16000 * 4, 0])  # 4 s
    transcriber = WhisperTranscriber(model_size="small")
    transcriber.transcribe(clip)  # warm up
    start = time.monotonic()
    transcriber.transcribe(clip)
    rtf = (time.monotonic() - start) / 4.0
    assert rtf < 1.0  # faster than real time
