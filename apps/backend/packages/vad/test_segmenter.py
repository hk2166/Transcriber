"""Unit tests for SpeechSegmenter, driven by a scripted fake VAD.

The state machine is what's under test, so the real ONNX model is replaced by
a FakeVAD returning one scripted probability per block — deterministic and
fast, with no audio or model dependency.
"""

import numpy as np

from packages.vad.segmenter import SpeechSegmenter

SAMPLE_RATE = 16_000
BLOCK = 1024  # 64 ms, matching the capture block size


class FakeVAD:
    """Returns a scripted confidence, one value per ``confidence()`` call."""

    def __init__(self, schedule: list[float]) -> None:
        self.schedule = list(schedule)
        self.i = 0

    def confidence(self, chunk) -> float:
        value = self.schedule[self.i] if self.i < len(self.schedule) else 0.0
        self.i += 1
        return value

    def reset(self) -> None:
        self.i = 0


def run(schedule: list[float], **kwargs) -> list:
    """Feed one silent block per scheduled confidence; return all segments."""
    seg = SpeechSegmenter(FakeVAD(schedule), **kwargs)
    segments = []
    for _ in schedule:
        segments.extend(seg.process(np.zeros((BLOCK, 1), np.float32)))
    tail = seg.flush()
    if tail is not None:
        segments.append(tail)
    return segments


def test_speech_silence_speech_yields_exactly_two_segments():
    schedule = [0.9] * 10 + [0.0] * 15 + [0.9] * 10 + [0.0] * 15
    segments = run(schedule, min_speech_ms=250, min_silence_ms=700, padding_ms=200)
    assert len(segments) == 2
    assert segments[0].start_ms < segments[0].end_ms <= segments[1].start_ms


def test_short_blip_below_min_speech_is_discarded():
    schedule = [0.9] * 1 + [0.0] * 15  # one 64 ms blip, min_speech is 250 ms
    segments = run(schedule, min_speech_ms=250, min_silence_ms=700, padding_ms=200)
    assert segments == []


def test_brief_pause_below_min_silence_does_not_split():
    # 5 silent blocks (~320 ms) is under the 700 ms min_silence.
    schedule = [0.9] * 10 + [0.0] * 5 + [0.9] * 10 + [0.0] * 15
    segments = run(schedule, min_speech_ms=250, min_silence_ms=700, padding_ms=200)
    assert len(segments) == 1


def test_flush_emits_speech_in_progress_at_stream_end():
    schedule = [0.9] * 10  # never returns to silence
    segments = run(schedule, min_speech_ms=250, min_silence_ms=700, padding_ms=200)
    assert len(segments) == 1


def test_is_speech_active_tracks_state():
    seg = SpeechSegmenter(
        FakeVAD([0.0, 0.9, 0.9, 0.0]),
        min_speech_ms=0,
        min_silence_ms=64,  # one block of silence ends the segment
        padding_ms=0,
    )
    states = []
    for _ in range(4):
        seg.process(np.zeros((BLOCK, 1), np.float32))
        states.append(seg.is_speech_active)
    assert states == [False, True, True, False]


def test_segment_audio_length_matches_timestamps():
    schedule = [0.9] * 10 + [0.0] * 15
    segments = run(schedule, min_speech_ms=250, min_silence_ms=700, padding_ms=200)
    assert len(segments) == 1
    seg = segments[0]
    expected = int((seg.end_ms - seg.start_ms) * SAMPLE_RATE / 1000)
    assert abs(len(seg.audio) - expected) <= BLOCK


def test_reset_allows_reuse():
    seg = SpeechSegmenter(FakeVAD([0.9] * 5 + [0.0] * 15), min_speech_ms=0)
    for _ in range(20):
        seg.process(np.zeros((BLOCK, 1), np.float32))
    seg.reset()
    assert seg.is_speech_active is False
