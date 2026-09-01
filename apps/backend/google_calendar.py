"""Read-only Google Calendar: events + attendees, and meeting↔event matching.

The identity anchor for the People foundation (migration 0004): after a
recording ends, the calendar event it overlapped tells us *who was in the
room* by email. Fetching uses the already-granted ``calendar.events`` scope
via :func:`google_service.access_token` (auto-refresh); everything else here
is pure and unit-testable.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

import google_service
from packages.storage import (
    add_meeting_attendee,
    upsert_calendar_event,
    upsert_person_by_email,
)

logger = logging.getLogger(__name__)

__all__ = [
    "Attendee",
    "CalendarEvent",
    "best_match",
    "fetch_events",
    "ingest_attendees",
]

_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

#: Local-parts that are mailing lists / robots, not humans — never a Person.
_ROLE_LOCALPARTS = {
    "team", "info", "support", "hello", "admin", "office", "all", "everyone",
    "notifications", "calendar-notification",
}
_ROLE_PREFIXES = ("no-reply", "noreply", "do-not-reply", "donotreply")


@dataclass
class Attendee:
    email: str
    display_name: str | None
    response_status: str | None  # accepted | declined | tentative | needsAction
    is_self: bool
    is_resource: bool  # meeting rooms etc. — never a person


@dataclass
class CalendarEvent:
    event_id: str
    title: str
    start_iso: str
    end_iso: str
    all_day: bool
    attendees: list[Attendee]


def fetch_events(time_min: datetime, time_max: datetime) -> list[CalendarEvent]:
    """Events on the primary calendar between ``time_min`` and ``time_max``.

    Raises :class:`~packages.integrations.google_oauth.GoogleAuthError` when
    Google isn't connected (``access_token`` knows), and httpx errors on
    network/API failure — callers treat both as "no calendar context".
    """
    token = google_service.access_token()
    response = httpx.get(
        _EVENTS_URL,
        params={
            "timeMin": _rfc3339(time_min),
            "timeMax": _rfc3339(time_max),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 50,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    response.raise_for_status()
    events = []
    for item in response.json().get("items", []):
        event = _parse_event(item)
        if event is not None:
            events.append(event)
    return events


def _rfc3339(moment: datetime) -> str:
    """Google requires an offset; naive datetimes are taken as local time."""
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.isoformat()


def _parse_event(item: dict) -> CalendarEvent | None:
    event_id = item.get("id")
    if not event_id:
        return None
    start, start_all_day = _parse_when(item.get("start") or {})
    end, end_all_day = _parse_when(item.get("end") or {})
    if start is None or end is None:
        return None
    attendees = [
        Attendee(
            email=str(raw.get("email", "")).strip().lower(),
            display_name=raw.get("displayName"),
            response_status=raw.get("responseStatus"),
            is_self=bool(raw.get("self")),
            is_resource=bool(raw.get("resource"))
            or str(raw.get("email", "")).endswith("resource.calendar.google.com"),
        )
        for raw in item.get("attendees", [])
        if raw.get("email")
    ]
    return CalendarEvent(
        event_id=event_id,
        title=item.get("summary") or "(untitled)",
        start_iso=start,
        end_iso=end,
        all_day=start_all_day or end_all_day,
        attendees=attendees,
    )


def _parse_when(when: dict) -> tuple[str | None, bool]:
    """Google start/end: ``dateTime`` (timed) or ``date`` (all-day)."""
    if when.get("dateTime"):
        return when["dateTime"], False
    if when.get("date"):
        return f"{when['date']}T00:00:00", True
    return None, False


# --- Time matching (pure) ------------------------------------------------------

def best_match(
    events: list[CalendarEvent],
    meeting_start: datetime,
    meeting_end: datetime,
    tolerance_min: int = 15,
) -> CalendarEvent | None:
    """The event whose time window overlaps the meeting most.

    Same max-overlap idiom as diarization's ``assign_speaker``, over the
    meeting window widened by ``tolerance_min`` (recordings rarely start
    exactly on the calendar slot). Guard rails:

    - all-day events never match (a birthday must not claim a stand-up);
    - ambiguity — a runner-up within 20% of the winner's overlap — matches
      NOTHING: a wrong identity link is worse than none.
    """
    window_start = meeting_start - timedelta(minutes=tolerance_min)
    window_end = meeting_end + timedelta(minutes=tolerance_min)

    best: CalendarEvent | None = None
    best_overlap = 0.0
    runner_up = 0.0
    for event in events:
        if event.all_day:
            continue
        start = _to_local_naive(event.start_iso)
        end = _to_local_naive(event.end_iso)
        if start is None or end is None:
            continue
        overlap = (min(end, window_end) - max(start, window_start)).total_seconds()
        if overlap <= 0:
            continue
        if overlap > best_overlap:
            best, best_overlap, runner_up = event, overlap, best_overlap
        elif overlap > runner_up:
            runner_up = overlap
    if best is not None and runner_up >= 0.8 * best_overlap:
        logger.info(
            "Calendar match ambiguous (%.0fs vs %.0fs overlap) — matching nothing.",
            best_overlap, runner_up,
        )
        return None
    return best


def _to_local_naive(iso: str) -> datetime | None:
    """Meeting timestamps are naive local; normalise event times to compare."""
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment


# --- Attendee ingestion (people foundation) ------------------------------------

def ingest_attendees(
    conn: sqlite3.Connection,
    meeting_id: int,
    event: CalendarEvent,
    self_email: str | None,
) -> int:
    """Upsert an event's human attendees as People linked to the meeting.

    Skips the connected account itself (their own meetings shouldn't list
    them as a contact), meeting-room resources, and role mailboxes.
    Idempotent: emails dedupe via ``upsert_person_by_email`` and the attendee
    link's primary key. Returns how many people were linked.
    """
    upsert_calendar_event(
        conn,
        event_id=event.event_id,
        title=event.title,
        start_iso=event.start_iso,
        end_iso=event.end_iso,
        attendees=[
            {"email": a.email, "display_name": a.display_name,
             "response_status": a.response_status}
            for a in event.attendees
        ],
        meeting_id=meeting_id,
    )
    me = (self_email or "").strip().lower()
    linked = 0
    for attendee in event.attendees:
        if not attendee.email or attendee.is_resource:
            continue
        if attendee.is_self or (me and attendee.email == me):
            continue
        if _is_role_mailbox(attendee.email):
            continue
        person_id = upsert_person_by_email(
            conn, attendee.email, display_name=attendee.display_name
        )
        add_meeting_attendee(conn, meeting_id, person_id, source="calendar")
        linked += 1
    return linked


def _is_role_mailbox(email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    return local in _ROLE_LOCALPARTS or local.startswith(_ROLE_PREFIXES)
