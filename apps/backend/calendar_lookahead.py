"""Pre-call prep: know who you're about to meet before the call starts.

A lifespan-owned task — a sibling of :func:`meeting_detect.poller` — refreshes
a 30-minute window of calendar events every two minutes while Google is
connected, resolving attendees to People as it goes. The status endpoint
re-evaluates that cache against the clock on every request, so the card
appears the minute an event comes within :data:`LEAD` of starting rather
than up to a refresh late.

Everything here is in memory: nothing is persisted, and dismissals die with
the process (one session). The timing and attendee rules are pure functions.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx

import google_service
from database import get_db
from google_calendar import (
    CalendarEvent,
    _is_role_mailbox,
    _to_local_naive,
    fetch_events,
)
from packages.integrations.google_oauth import GoogleAuthError
from packages.storage import Person, get_people_by_emails

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 120
#: How far ahead each refresh looks.
HORIZON = timedelta(minutes=30)
#: How long before its start an event becomes "upcoming".
LEAD = timedelta(minutes=10)


@dataclass
class Candidate:
    """A fetched event with its attendees already resolved to People."""

    event: CalendarEvent
    people: list[dict[str, Any]] = field(default_factory=list)  # {id, display_name}
    unknown_count: int = 0


_cache: list[Candidate] = []
_dismissed: set[str] = set()
_last_error: str | None = None


# --- Pure rules ----------------------------------------------------------------

def pick_upcoming(
    events: Iterable[CalendarEvent],
    now: datetime,
    dismissed: Iterable[str] = (),
    *,
    lead: timedelta = LEAD,
) -> CalendarEvent | None:
    """The event to prep for: the earliest one that starts within ``lead`` (or
    is already underway) and hasn't ended — skipping all-day events and
    dismissed ids. ``now`` is naive local time, like meeting timestamps."""
    skip = set(dismissed)
    best: CalendarEvent | None = None
    best_start: datetime | None = None
    for event in events:
        if event.all_day or event.event_id in skip:
            continue
        start = _to_local_naive(event.start_iso)
        end = _to_local_naive(event.end_iso)
        if start is None or end is None:
            continue
        if now < start - lead or now >= end:
            continue
        if best_start is None or start < best_start:
            best, best_start = event, start
    return best


def resolve_people(
    event: CalendarEvent,
    people_by_email: Mapping[str, Person],
    self_email: str | None,
) -> tuple[list[dict[str, Any]], int]:
    """Human attendees → ``[{id, display_name}]`` for known people (most-met
    first), plus how many humans we have no record of. Same skips as
    ``ingest_attendees``: the connected account, rooms, role mailboxes."""
    me = (self_email or "").strip().lower()
    known: list[tuple[Person, str]] = []
    seen: set[int] = set()
    unknown = 0
    for attendee in event.attendees:
        email = attendee.email
        if not email or attendee.is_resource or attendee.is_self or email == me:
            continue
        if _is_role_mailbox(email):
            continue
        person = people_by_email.get(email)
        if person is None:
            unknown += 1
            continue
        if person.id in seen:
            continue
        seen.add(person.id)
        label = (
            person.display_name
            or attendee.display_name
            or person.primary_email
            or email
        )
        known.append((person, label))
    known.sort(key=lambda pair: (-pair[0].meeting_count, pair[1].lower()))
    return [{"id": p.id, "display_name": label} for p, label in known], unknown


def payload(
    candidates: Iterable[Candidate],
    now: datetime,
    dismissed: Iterable[str] = (),
) -> dict[str, Any] | None:
    """The status-endpoint shape for the event to prep for, or ``None``."""
    by_id = {c.event.event_id: c for c in candidates}
    event = pick_upcoming((c.event for c in by_id.values()), now, dismissed)
    if event is None:
        return None
    candidate = by_id[event.event_id]
    return {
        "event_id": event.event_id,
        "event_title": event.title,
        "start_iso": event.start_iso,
        "people": list(candidate.people),
        "unknown_count": candidate.unknown_count,
    }


# --- Process state ---------------------------------------------------------------

def current(now: datetime | None = None) -> dict[str, Any] | None:
    """What the UI should show right now (re-evaluated per call, no I/O)."""
    return payload(_cache, now or datetime.now(), _dismissed)


def dismiss(event_id: str) -> None:
    """Hide an event's card for the rest of this process."""
    _dismissed.add(event_id)


def refresh(now: datetime | None = None) -> None:
    """Fetch the next 30 minutes and resolve attendees (blocking — run in a
    thread). Events with nobody but you are dropped: nothing to prep for."""
    global _cache, _last_error
    status = google_service.status()
    if not status.get("connected"):
        _cache = []
        return
    now = now or datetime.now()
    try:
        events = fetch_events(now, now + HORIZON)
    except (GoogleAuthError, httpx.HTTPError) as exc:
        message = str(exc) or exc.__class__.__name__
        if message != _last_error:
            logger.warning("Calendar lookahead unavailable: %s", message)
            _last_error = message
        _cache = []
        return
    _last_error = None
    timed = [event for event in events if not event.all_day]
    emails = {a.email for event in timed for a in event.attendees if a.email}
    known = get_people_by_emails(get_db(), emails)
    me = status.get("email")
    candidates = [
        Candidate(event, *resolve_people(event, known, me)) for event in timed
    ]
    _cache = [c for c in candidates if c.people or c.unknown_count]


async def refresher() -> None:
    """Background task: keep the cache warm. Cancelled at shutdown."""
    while True:
        try:
            await asyncio.to_thread(refresh)
        except Exception:
            logger.exception("Calendar lookahead failed.")
        await asyncio.sleep(REFRESH_SECONDS)
