"""Repository tests on an in-memory database (migrations applied fresh each test)."""

from datetime import datetime

import pytest

from packages.storage import (
    connect,
    create_meeting,
    create_speakers,
    delete_meeting,
    end_meeting,
    get_meeting,
    get_meetings,
    get_segments,
    get_speakers,
    insert_segment,
    rename_speaker,
    set_meeting_status,
    set_segment_speaker,
)


@pytest.fixture
def conn():
    connection = connect(":memory:")
    yield connection
    connection.close()


def _new_meeting(conn, source="both"):
    return create_meeting(
        conn,
        source=source,
        wav_path="/tmp/x.wav",
        started_at=datetime(2026, 8, 14, 9, 30),
    )


def test_migrations_create_all_tables(conn):
    names = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"meetings", "speakers", "transcript_segments", "summaries"} <= names


def test_create_meeting_sets_title_and_status(conn):
    meeting_id = _new_meeting(conn)
    meeting = get_meeting(conn, meeting_id)
    assert meeting is not None
    assert meeting.title == "Meeting — Aug 14, 9:30 AM"
    assert meeting.status == "recording"
    assert meeting.source == "both"
    assert meeting.ended_at is None


def test_insert_and_get_segments_in_time_order(conn):
    meeting_id = _new_meeting(conn)
    insert_segment(conn, meeting_id, text="second", start_ms=5000, end_ms=6000,
                   language="en", confidence=0.9)
    insert_segment(conn, meeting_id, text="first", start_ms=1000, end_ms=2000,
                   language="en", confidence=0.8)

    segments = get_segments(conn, meeting_id)
    assert [s.text for s in segments] == ["first", "second"]
    assert segments[0].start_ms == 1000
    assert segments[0].confidence == 0.8


def test_segment_count_reported(conn):
    meeting_id = _new_meeting(conn)
    for i in range(3):
        insert_segment(conn, meeting_id, text=f"s{i}", start_ms=i * 1000,
                       end_ms=i * 1000 + 500, language="en", confidence=0.7)
    assert get_meeting(conn, meeting_id).segment_count == 3


def test_end_meeting_sets_ended_and_status(conn):
    meeting_id = _new_meeting(conn)
    end_meeting(conn, meeting_id, ended_at=datetime(2026, 8, 14, 9, 45))
    meeting = get_meeting(conn, meeting_id)
    assert meeting.status == "ready"
    assert meeting.ended_at is not None


def test_get_meetings_newest_first(conn):
    a = create_meeting(conn, source="mic", wav_path=None,
                       started_at=datetime(2026, 8, 14, 9, 0))
    b = create_meeting(conn, source="mic", wav_path=None,
                       started_at=datetime(2026, 8, 14, 10, 0))
    ids = [m.id for m in get_meetings(conn)]
    assert ids == [b, a]


def test_delete_meeting_cascades_to_segments(conn):
    meeting_id = _new_meeting(conn)
    insert_segment(conn, meeting_id, text="x", start_ms=0, end_ms=100,
                   language="en", confidence=0.5)
    delete_meeting(conn, meeting_id)
    assert get_meeting(conn, meeting_id) is None
    assert get_segments(conn, meeting_id) == []


def test_get_missing_meeting_returns_none(conn):
    assert get_meeting(conn, 999) is None


def test_create_speakers_deterministic_labels_and_colors(conn):
    meeting_id = _new_meeting(conn)
    mapping = create_speakers(conn, meeting_id, ["SPEAKER_01", "SPEAKER_00", "SPEAKER_00"])
    assert set(mapping) == {"SPEAKER_00", "SPEAKER_01"}

    speakers = get_speakers(conn, meeting_id)
    assert [s.label for s in speakers] == ["Speaker 1", "Speaker 2"]
    assert speakers[0].color != speakers[1].color
    # sorted label order: SPEAKER_00 → Speaker 1
    assert mapping["SPEAKER_00"] == speakers[0].id


def test_set_segment_speaker_and_readback(conn):
    meeting_id = _new_meeting(conn)
    seg_id = insert_segment(conn, meeting_id, text="hi", start_ms=0, end_ms=500,
                            language="en", confidence=0.9)
    mapping = create_speakers(conn, meeting_id, ["SPEAKER_00"])
    set_segment_speaker(conn, seg_id, mapping["SPEAKER_00"])
    assert get_segments(conn, meeting_id)[0].speaker_id == mapping["SPEAKER_00"]


def test_rename_speaker(conn):
    meeting_id = _new_meeting(conn)
    mapping = create_speakers(conn, meeting_id, ["SPEAKER_00"])
    speaker_id = mapping["SPEAKER_00"]
    assert rename_speaker(conn, speaker_id, "Alice") is True
    assert get_speakers(conn, meeting_id)[0].name == "Alice"
    assert rename_speaker(conn, 999, "Nobody") is False


def test_set_meeting_status(conn):
    meeting_id = _new_meeting(conn)
    set_meeting_status(conn, meeting_id, "processing")
    assert get_meeting(conn, meeting_id).status == "processing"
