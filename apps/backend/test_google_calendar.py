"""Calendar-attendee ingestion: matcher, parsing, fetch (mocked), and dedup."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

import google_calendar
import google_service
from google_calendar import Attendee, CalendarEvent, best_match, ingest_attendees
from packages.storage import (
    connect,
    create_meeting,
    get_calendar_event_for_meeting,
    get_meeting_ids_for_person,
    get_people,
)


def _event(event_id, start, end, *, all_day=False, attendees=None, title="Standup"):
    return CalendarEvent(
        event_id=event_id, title=title, start_iso=start, end_iso=end,
        all_day=all_day, attendees=attendees or [],
    )


def _attendee(email, name=None, *, is_self=False, is_resource=False):
    return Attendee(email=email, display_name=name, response_status="accepted",
                    is_self=is_self, is_resource=is_resource)


# --- best_match (pure) ---------------------------------------------------------

MEETING_START = datetime(2026, 9, 1, 10, 0)
MEETING_END = datetime(2026, 9, 1, 10, 45)


def test_match_picks_max_overlap():
    events = [
        _event("early", "2026-09-01T08:00:00", "2026-09-01T09:00:00"),
        _event("right", "2026-09-01T10:00:00", "2026-09-01T11:00:00"),
    ]
    assert best_match(events, MEETING_START, MEETING_END).event_id == "right"


def test_match_tolerates_early_start():
    # Recording began 10 min before the slot — still inside the ±15 min window.
    events = [_event("slot", "2026-09-01T10:10:00", "2026-09-01T11:00:00")]
    assert best_match(events, MEETING_START, MEETING_END).event_id == "slot"


def test_ambiguous_overlap_matches_nothing():
    # Two candidates within 20% of each other — guessing risks a wrong link.
    events = [
        _event("a", "2026-09-01T09:30:00", "2026-09-01T10:30:00"),
        _event("b", "2026-09-01T10:15:00", "2026-09-01T11:15:00"),
    ]
    assert best_match(events, MEETING_START, MEETING_END) is None


def test_clear_winner_beats_minor_overlap():
    events = [
        _event("winner", "2026-09-01T10:00:00", "2026-09-01T11:00:00"),
        _event("brush", "2026-09-01T09:00:00", "2026-09-01T10:00:05"),
    ]
    assert best_match(events, MEETING_START, MEETING_END).event_id == "winner"


def test_no_candidates_matches_nothing():
    events = [_event("other-day", "2026-09-02T10:00:00", "2026-09-02T11:00:00")]
    assert best_match(events, MEETING_START, MEETING_END) is None
    assert best_match([], MEETING_START, MEETING_END) is None


def test_all_day_events_never_match():
    events = [_event("birthday", "2026-09-01T00:00:00", "2026-09-02T00:00:00",
                     all_day=True)]
    assert best_match(events, MEETING_START, MEETING_END) is None


def test_timezone_aware_event_times_compare_cleanly():
    # Whatever the wire offset, the event normalises to local time for overlap.
    local = datetime(2026, 9, 1, 10, 0).astimezone()
    iso_start = local.isoformat()
    iso_end = local.replace(hour=11).isoformat()
    events = [_event("tz", iso_start, iso_end)]
    assert best_match(events, MEETING_START, MEETING_END).event_id == "tz"


# --- parsing -------------------------------------------------------------------

def test_parse_event_handles_datetime_and_date():
    timed = google_calendar._parse_event({
        "id": "e1", "summary": "Sync",
        "start": {"dateTime": "2026-09-01T10:00:00+05:30"},
        "end": {"dateTime": "2026-09-01T10:30:00+05:30"},
        "attendees": [
            {"email": "Sarah@x.com", "displayName": "Sarah", "responseStatus": "accepted"},
            {"email": "room-3@resource.calendar.google.com", "resource": True},
        ],
    })
    assert timed.all_day is False
    assert timed.attendees[0].email == "sarah@x.com"  # lowercased
    assert timed.attendees[1].is_resource is True

    all_day = google_calendar._parse_event({
        "id": "e2", "start": {"date": "2026-09-01"}, "end": {"date": "2026-09-02"},
    })
    assert all_day.all_day is True
    assert all_day.title == "(untitled)"
    assert google_calendar._parse_event({"start": {}, "end": {}}) is None


# --- fetch (mocked httpx + token) ------------------------------------------------

def test_fetch_events_parses_api_response(monkeypatch):
    monkeypatch.setattr(google_service, "access_token", lambda: "tok-123")
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(url=url, params=params, headers=headers)
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"items": [
                {"id": "e1", "summary": "Sync",
                 "start": {"dateTime": "2026-09-01T10:00:00+05:30"},
                 "end": {"dateTime": "2026-09-01T10:30:00+05:30"},
                 "attendees": [{"email": "a@x.com"}]},
                {"id": None},  # unparseable → dropped
            ]},
        )

    monkeypatch.setattr(google_calendar.httpx, "get", fake_get)
    events = google_calendar.fetch_events(
        datetime(2026, 9, 1, 8, 0), datetime(2026, 9, 1, 12, 0)
    )
    assert [e.event_id for e in events] == ["e1"]
    assert captured["headers"]["Authorization"] == "Bearer tok-123"
    assert captured["params"]["singleEvents"] == "true"
    # RFC3339 with an offset, as Google requires.
    assert "+" in captured["params"]["timeMin"] or "Z" in captured["params"]["timeMin"]


def test_fetch_raises_cleanly_when_not_connected(monkeypatch):
    from packages.integrations.google_oauth import GoogleAuthError

    def raise_not_connected():
        raise GoogleAuthError("Google isn't connected.")

    monkeypatch.setattr(google_service, "access_token", raise_not_connected)
    with pytest.raises(GoogleAuthError):
        google_calendar.fetch_events(MEETING_START, MEETING_END)


# --- ingest_attendees (in-memory db) ---------------------------------------------

@pytest.fixture
def conn():
    connection = connect(":memory:")
    yield connection
    connection.close()


def test_ingest_links_humans_skips_self_roles_resources(conn):
    meeting_id = create_meeting(conn, source="both", wav_path=None,
                                started_at=datetime(2026, 9, 1, 10, 0))
    event = _event(
        "ev1", "2026-09-01T10:00:00", "2026-09-01T11:00:00",
        attendees=[
            _attendee("sarah@x.com", "Sarah"),
            _attendee("dev@y.com"),
            _attendee("hemant@inboxkit.com", is_self=True),   # the account itself
            _attendee("no-reply@calendar.google.com"),         # robot
            _attendee("team@x.com"),                           # role mailbox
            _attendee("room-3@resource.calendar.google.com", is_resource=True),
        ],
    )

    linked = ingest_attendees(conn, meeting_id, event, "hemant@inboxkit.com")

    assert linked == 2
    people = get_people(conn)
    assert sorted(p.primary_email for p in people) == ["dev@y.com", "sarah@x.com"]
    assert all(get_meeting_ids_for_person(conn, p.id) == [meeting_id] for p in people)
    cached = get_calendar_event_for_meeting(conn, meeting_id)
    assert cached is not None and cached.event_id == "ev1"
    assert len(cached.attendees) == 6  # raw roster cached even where skipped


def test_ingest_is_idempotent_and_dedupes_by_email(conn):
    meeting_id = create_meeting(conn, source="both", wav_path=None,
                                started_at=datetime(2026, 9, 1, 10, 0))
    event = _event("ev1", "2026-09-01T10:00:00", "2026-09-01T11:00:00",
                   attendees=[_attendee("Sarah@X.com", "Sarah")])

    ingest_attendees(conn, meeting_id, event, None)
    ingest_attendees(conn, meeting_id, event, None)  # re-run: same person/link

    people = get_people(conn)
    assert len(people) == 1
    assert people[0].primary_email == "sarah@x.com"
    assert people[0].meeting_count == 1  # link stayed unique


def test_ingest_second_meeting_same_person_accumulates(conn):
    first = create_meeting(conn, source="both", wav_path=None,
                           started_at=datetime(2026, 9, 1, 10, 0))
    second = create_meeting(conn, source="both", wav_path=None,
                            started_at=datetime(2026, 9, 2, 10, 0))
    event1 = _event("ev1", "2026-09-01T10:00:00", "2026-09-01T11:00:00",
                    attendees=[_attendee("sarah@x.com")])
    event2 = _event("ev2", "2026-09-02T10:00:00", "2026-09-02T11:00:00",
                    attendees=[_attendee("sarah@x.com")])

    ingest_attendees(conn, first, event1, None)
    ingest_attendees(conn, second, event2, None)

    people = get_people(conn)
    assert len(people) == 1 and people[0].meeting_count == 2
    assert get_meeting_ids_for_person(conn, people[0].id) == [second, first]
