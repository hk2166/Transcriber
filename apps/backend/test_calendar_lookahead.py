"""Calendar lookahead: trigger window, dismissal, attendee resolution, endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import calendar_lookahead
from calendar_lookahead import Candidate, payload, pick_upcoming, resolve_people
from google_calendar import Attendee, CalendarEvent
from main import app
from packages.integrations.google_oauth import GoogleAuthError
from packages.storage import Person, connect, upsert_person_by_email

NOW = datetime(2026, 9, 4, 10, 0)


def event(
    event_id="evt",
    title="Standup",
    *,
    start_in=5,
    minutes=30,
    all_day=False,
    attendees=(),
    base=NOW,
):
    start = base + timedelta(minutes=start_in)
    end = start + timedelta(minutes=minutes)
    return CalendarEvent(
        event_id=event_id,
        title=title,
        start_iso=start.isoformat(),
        end_iso=end.isoformat(),
        all_day=all_day,
        attendees=list(attendees),
    )


def person(id, name, email, met):
    return Person(
        id=id, display_name=name, primary_email=email, notes="",
        meeting_count=met, last_met=None, created_at="",
    )


def attendee(email, name=None, *, is_self=False, is_resource=False):
    return Attendee(
        email=email, display_name=name, response_status=None,
        is_self=is_self, is_resource=is_resource,
    )


# --- Trigger window ------------------------------------------------------------

def test_event_nine_minutes_out_fires():
    assert pick_upcoming([event(start_in=9)], NOW) is not None


def test_event_forty_minutes_out_does_not_fire():
    assert pick_upcoming([event(start_in=40)], NOW) is None


def test_lead_boundary_is_inclusive():
    assert pick_upcoming([event(start_in=10)], NOW) is not None
    assert pick_upcoming([event(start_in=10)], NOW - timedelta(seconds=1)) is None


def test_underway_event_fires_until_it_ends():
    running = event(start_in=-3, minutes=30)
    assert pick_upcoming([running], NOW) is running
    assert pick_upcoming([running], NOW + timedelta(minutes=27)) is None


def test_all_day_events_never_fire():
    assert pick_upcoming([event(start_in=5, all_day=True)], NOW) is None


def test_earliest_qualifying_event_wins():
    later = event("b", start_in=8)
    sooner = event("a", start_in=2)
    assert pick_upcoming([later, sooner], NOW) is sooner


def test_dismissed_stays_dismissed():
    evt = event(start_in=5)
    assert pick_upcoming([evt], NOW, dismissed={"evt"}) is None
    later = NOW + timedelta(minutes=4)  # closer to the start — still gone
    assert pick_upcoming([evt], later, dismissed={"evt"}) is None


def test_unparseable_times_are_skipped():
    bad = CalendarEvent("x", "?", "nope", "nope", all_day=False, attendees=[])
    assert pick_upcoming([bad], NOW) is None


# --- Attendee resolution -------------------------------------------------------

def test_resolve_orders_known_people_by_history_and_counts_strangers():
    sarah = person(1, "Sarah", "sarah@x.com", met=1)
    dana = person(2, None, "dana@x.com", met=4)
    evt = event(attendees=[
        attendee("me@x.com", is_self=True),
        attendee("room@resource.calendar.google.com", is_resource=True),
        attendee("team@x.com"),  # role mailbox
        attendee("sarah@x.com", "Sarah Lee"),
        attendee("dana@x.com", "Dana Q"),
        attendee("newbie@x.com", "New Person"),  # no record yet
    ])
    known = {"sarah@x.com": sarah, "dana@x.com": dana}
    people, unknown = resolve_people(evt, known, "me@x.com")
    assert [p["id"] for p in people] == [2, 1]  # most-met first
    assert people[0]["display_name"] == "Dana Q"  # calendar name fills a blank record
    assert people[1]["display_name"] == "Sarah"  # our record beats the calendar's
    assert unknown == 1


def test_resolve_skips_the_connected_account_by_email_too():
    evt = event(attendees=[attendee("me@x.com")])  # no self flag from Google
    assert resolve_people(evt, {}, "Me@X.com") == ([], 0)


# --- Payload + endpoint --------------------------------------------------------

def test_payload_shape_and_expiry():
    evt = event(start_in=8)
    cand = Candidate(evt, people=[{"id": 1, "display_name": "Sarah"}], unknown_count=2)
    assert payload([cand], NOW) == {
        "event_id": "evt",
        "event_title": "Standup",
        "start_iso": evt.start_iso,
        "people": [{"id": 1, "display_name": "Sarah"}],
        "unknown_count": 2,
    }
    assert payload([cand], NOW + timedelta(minutes=45)) is None


@pytest.fixture
def lookahead(monkeypatch):
    monkeypatch.setattr(calendar_lookahead, "_cache", [])
    monkeypatch.setattr(calendar_lookahead, "_dismissed", set())
    monkeypatch.setattr(calendar_lookahead, "_last_error", None)
    return calendar_lookahead


client = TestClient(app)


def test_status_endpoint_carries_upcoming(lookahead):
    assert client.get("/system/meeting-app").json()["upcoming"] is None
    evt = event(start_in=5, base=datetime.now())
    lookahead._cache.append(
        Candidate(evt, people=[{"id": 1, "display_name": "Sarah"}], unknown_count=1)
    )
    upcoming = client.get("/system/meeting-app").json()["upcoming"]
    assert set(upcoming) == {
        "event_id", "event_title", "start_iso", "people", "unknown_count",
    }
    assert upcoming["event_title"] == "Standup"
    assert upcoming["people"] == [{"id": 1, "display_name": "Sarah"}]
    assert upcoming["unknown_count"] == 1


def test_dismiss_endpoint_hides_the_event_for_the_session(lookahead):
    lookahead._cache.append(Candidate(event(start_in=5, base=datetime.now())))
    assert client.get("/system/meeting-app").json()["upcoming"]["event_id"] == "evt"
    response = client.post("/system/meeting-app/dismiss", json={"event_id": "evt"})
    assert response.json() == {"dismissed": "evt"}
    assert client.get("/system/meeting-app").json()["upcoming"] is None


# --- Refresh (I/O boundary, stubbed) -------------------------------------------

def connected(monkeypatch, lookahead, email="me@x.com"):
    monkeypatch.setattr(
        lookahead.google_service, "status",
        lambda: {"has_client": True, "connected": True, "email": email},
    )


def test_refresh_resolves_attendees_and_drops_solo_events(monkeypatch, lookahead):
    conn = connect(":memory:")
    sarah = upsert_person_by_email(conn, "sarah@x.com", display_name="Sarah")
    monkeypatch.setattr(lookahead, "get_db", lambda: conn)
    connected(monkeypatch, lookahead)
    focus = event("focus", "Focus time", start_in=3)  # nobody to prep for
    standup = event("standup", start_in=5, attendees=[
        attendee("me@x.com", is_self=True),
        attendee("sarah@x.com"),
        attendee("new@x.com"),
    ])
    monkeypatch.setattr(lookahead, "fetch_events", lambda a, b: [focus, standup])

    lookahead.refresh(NOW)

    assert [c.event.event_id for c in lookahead._cache] == ["standup"]
    assert lookahead._cache[0].people == [{"id": sarah, "display_name": "Sarah"}]
    assert lookahead._cache[0].unknown_count == 1
    assert lookahead.current(NOW)["event_id"] == "standup"


def test_refresh_without_google_clears_and_never_fetches(monkeypatch, lookahead):
    lookahead._cache.append(Candidate(event()))
    monkeypatch.setattr(
        lookahead.google_service, "status",
        lambda: {"has_client": True, "connected": False, "email": None},
    )
    monkeypatch.setattr(
        lookahead, "fetch_events",
        lambda a, b: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    lookahead.refresh(NOW)
    assert lookahead._cache == []


def test_refresh_treats_auth_and_network_errors_as_no_calendar(monkeypatch, lookahead):
    connected(monkeypatch, lookahead)
    lookahead._cache.append(Candidate(event()))
    monkeypatch.setattr(
        lookahead, "fetch_events",
        lambda a, b: (_ for _ in ()).throw(GoogleAuthError("token revoked")),
    )
    lookahead.refresh(NOW)  # no raise
    assert lookahead._cache == []
    assert lookahead._last_error == "token revoked"
