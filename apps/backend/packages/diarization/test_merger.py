"""Tests for speaker/segment overlap assignment (no model required)."""

from packages.diarization import SpeakerTurn, assign_speaker, assign_speakers

TURNS = [
    SpeakerTurn("SPEAKER_00", 0, 5000),
    SpeakerTurn("SPEAKER_01", 5000, 10000),
    SpeakerTurn("SPEAKER_00", 10000, 15000),
]


def test_segment_inside_one_turn():
    assert assign_speaker(1000, 4000, TURNS) == "SPEAKER_00"
    assert assign_speaker(6000, 9000, TURNS) == "SPEAKER_01"


def test_segment_straddling_two_turns_takes_majority():
    # 3800–5200: 1200 ms in SPEAKER_00, 200 ms in SPEAKER_01.
    assert assign_speaker(3800, 5200, TURNS) == "SPEAKER_00"
    # 4800–5900: 200 ms in SPEAKER_00, 900 ms in SPEAKER_01.
    assert assign_speaker(4800, 5900, TURNS) == "SPEAKER_01"


def test_segment_in_gap_returns_none():
    gapped = [SpeakerTurn("SPEAKER_00", 0, 1000), SpeakerTurn("SPEAKER_01", 5000, 6000)]
    assert assign_speaker(2000, 3000, gapped) is None


def test_no_turns_returns_none():
    assert assign_speaker(0, 1000, []) is None


def test_assign_speakers_batch():
    segments = [(1000, 4000), (6000, 9000), (11000, 14000)]
    assert assign_speakers(segments, TURNS) == [
        "SPEAKER_00",
        "SPEAKER_01",
        "SPEAKER_00",
    ]
