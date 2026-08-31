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
    get_summary,
    insert_segment,
    rename_speaker,
    replace_segments,
    save_summary,
    set_meeting_status,
    set_meeting_title,
    set_segment_speaker,
)


class _Seg:
    """Minimal stand-in for a TranscriptSegment (duck-typed by replace_segments)."""

    def __init__(self, text, start_ms, end_ms, language="en", confidence=0.95):
        self.text = text
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.language = language
        self.confidence = confidence


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


def test_replace_segments_swaps_the_whole_transcript(conn):
    meeting_id = _new_meeting(conn)
    insert_segment(conn, meeting_id, text="rough one", start_ms=0, end_ms=900,
                   language="en", confidence=0.4)
    insert_segment(conn, meeting_id, text="rough two", start_ms=1000, end_ms=1800,
                   language="en", confidence=0.4)

    count = replace_segments(conn, meeting_id, [
        _Seg("Refined one.", 0, 950),
        _Seg("Refined two.", 1000, 1850),
        _Seg("Refined three.", 2000, 2600),
    ])

    assert count == 3
    segments = get_segments(conn, meeting_id)
    assert [s.text for s in segments] == ["Refined one.", "Refined two.", "Refined three."]
    # Fresh segments start unattributed — diarization re-runs after the refine.
    assert all(s.speaker_id is None for s in segments)


def test_replace_segments_is_atomic_on_bad_input(conn):
    meeting_id = _new_meeting(conn)
    insert_segment(conn, meeting_id, text="keep me", start_ms=0, end_ms=900,
                   language="en", confidence=0.9)

    class _Broken:
        text = "boom"
        start_ms = 0
        end_ms = 100
        language = "en"

        @property
        def confidence(self):  # blows up mid-insert
            raise ValueError("no confidence")

    with pytest.raises(ValueError):
        replace_segments(conn, meeting_id, [_Seg("Refined.", 0, 900), _Broken()])

    # The transaction rolled back — the original transcript survives intact.
    assert [s.text for s in get_segments(conn, meeting_id)] == ["keep me"]


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


def test_set_meeting_title(conn):
    meeting_id = _new_meeting(conn)
    set_meeting_title(conn, meeting_id, "Q3 Roadmap Review")
    assert get_meeting(conn, meeting_id).title == "Q3 Roadmap Review"


def test_save_and_get_summary_roundtrip(conn):
    meeting_id = _new_meeting(conn)
    assert get_summary(conn, meeting_id) is None
    save_summary(
        conn, meeting_id,
        summary="We reviewed the roadmap.",
        key_points=["a", "b"], action_items=["email"], decisions=[],
        open_questions=["when?"],
    )
    stored = get_summary(conn, meeting_id)
    assert stored.summary == "We reviewed the roadmap."
    assert stored.key_points == ["a", "b"]
    assert stored.decisions == []


def test_save_summary_replaces_existing(conn):
    meeting_id = _new_meeting(conn)
    save_summary(conn, meeting_id, summary="first", key_points=[], action_items=[],
                 decisions=[], open_questions=[])
    save_summary(conn, meeting_id, summary="second", key_points=["x"], action_items=[],
                 decisions=[], open_questions=[])
    stored = get_summary(conn, meeting_id)
    assert stored.summary == "second"
    assert stored.key_points == ["x"]


# ---------------------------------------------------------------------------
# Segment editing + action items (feature round, Aug 2026)
# ---------------------------------------------------------------------------

from packages.storage import (  # noqa: E402
    get_action_items,
    replace_action_items,
    set_action_item_done,
    update_segment_text,
)


def test_update_segment_text(conn):
    meeting_id = _new_meeting(conn)
    segment_id = insert_segment(
        conn, meeting_id, text="helo wrld", start_ms=0, end_ms=900,
        language="en", confidence=0.9,
    )
    assert update_segment_text(conn, segment_id, "hello world") is True
    assert get_segments(conn, meeting_id)[0].text == "hello world"


def test_update_segment_text_unknown_id(conn):
    assert update_segment_text(conn, 999, "nope") is False


def test_action_items_roundtrip(conn):
    meeting_id = _new_meeting(conn)
    replace_action_items(conn, meeting_id, ["Send the deck", "Book the review"])
    items = get_action_items(conn)
    assert [i.text for i in items] == ["Send the deck", "Book the review"]
    assert all(i.done is False for i in items)
    assert items[0].meeting_id == meeting_id
    assert items[0].meeting_title  # joined from meetings


def test_action_item_done_toggle(conn):
    meeting_id = _new_meeting(conn)
    replace_action_items(conn, meeting_id, ["Send the deck"])
    item = get_action_items(conn)[0]
    assert set_action_item_done(conn, item.id, True) is True
    assert get_action_items(conn)[0].done is True
    assert set_action_item_done(conn, 999, True) is False


def test_action_items_done_survives_resummarize(conn):
    meeting_id = _new_meeting(conn)
    replace_action_items(conn, meeting_id, ["Send the deck", "Book the review"])
    item = get_action_items(conn)[0]
    set_action_item_done(conn, item.id, True)
    # Re-summarise keeps one text, changes the other.
    replace_action_items(conn, meeting_id, ["Send the deck", "Email the notes"])
    by_text = {i.text: i.done for i in get_action_items(conn)}
    assert by_text == {"Send the deck": True, "Email the notes": False}


def test_action_items_cascade_on_delete(conn):
    meeting_id = _new_meeting(conn)
    replace_action_items(conn, meeting_id, ["Send the deck"])
    delete_meeting(conn, meeting_id)
    assert get_action_items(conn) == []


# ---------------------------------------------------------------------------
# Sync proposals (integrations, Aug 2026)
# ---------------------------------------------------------------------------

from packages.storage import (  # noqa: E402
    get_proposal,
    get_proposals,
    insert_proposals,
    mark_proposals_stale,
    set_proposal_result,
    set_proposal_status,
    update_proposal,
)


def _seed_proposals(conn):
    meeting_id = _new_meeting(conn)
    insert_proposals(conn, meeting_id, [
        ("reminder", "apple-reminders", "Freeze the build", "ctx", {}),
        ("event", "apple-calendar", "Design review", "ctx",
         {"start_iso": "2026-08-27T14:00", "duration_min": 45}),
    ])
    return meeting_id


def test_proposals_roundtrip(conn):
    meeting_id = _seed_proposals(conn)
    items = get_proposals(conn, meeting_id)
    assert [p.kind for p in items] == ["reminder", "event"]
    assert items[1].payload["duration_min"] == 45
    assert all(p.status == "proposed" for p in items)


def test_proposal_edit_and_skip(conn):
    meeting_id = _seed_proposals(conn)
    first = get_proposals(conn, meeting_id)[0]
    assert update_proposal(conn, first.id, title="Freeze by Wed") is True
    set_proposal_status(conn, first.id, "skipped")
    refreshed = get_proposal(conn, first.id)
    assert (refreshed.title, refreshed.status) == ("Freeze by Wed", "skipped")


def test_proposal_apply_result_and_idempotence(conn):
    meeting_id = _seed_proposals(conn)
    first = get_proposals(conn, meeting_id)[0]
    set_proposal_result(conn, first.id, status="applied", external_ref="uid-1")
    applied = get_proposal(conn, first.id)
    assert (applied.status, applied.external_ref) == ("applied", "uid-1")
    assert applied.applied_at is not None
    # applied rows resist status flips and edits
    assert set_proposal_status(conn, first.id, "skipped") is False
    assert update_proposal(conn, first.id, title="nope") is False


def test_stale_hides_unapplied_keeps_applied(conn):
    meeting_id = _seed_proposals(conn)
    first, second = get_proposals(conn, meeting_id)
    set_proposal_result(conn, first.id, status="applied", external_ref="uid-1")
    mark_proposals_stale(conn, meeting_id)
    remaining = get_proposals(conn, meeting_id)
    assert [p.id for p in remaining] == [first.id]  # applied survives, rest hidden


def test_proposals_cascade_on_meeting_delete(conn):
    meeting_id = _seed_proposals(conn)
    delete_meeting(conn, meeting_id)
    assert get_proposals(conn, meeting_id) == []
