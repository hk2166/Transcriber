"""Apple Reminders / Calendar / Notes via AppleScript (osascript).

Local-only targets: no cloud, no OAuth, no new dependencies — works in the
frozen bundle. Everything lands in a Confab-named list/calendar/folder so it's
easy to find and easy to purge, and never clobbers the user's own containers.

The first apply per app triggers macOS's automation consent prompt
("Confab wants to control Reminders"). A denial surfaces as a clear
per-card error, not a crash.

AppleScript is built from user-editable text, so every interpolated string
goes through :func:`_quote` — quote/backslash escaping here is the classic
injection bug (and is unit-tested with an injected runner).
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta

from packages.integrations.base import (
    AppliedRef,
    IntegrationError,
    MeetingContext,
    ProposalDraft,
)

logger = logging.getLogger(__name__)

__all__ = ["AppleCalendar", "AppleNotes", "AppleReminders", "run_osascript"]

CONTAINER = "Confab"
_TIMEOUT_S = 45  # Calendar.app can be slow to launch


def run_osascript(script: str) -> str:
    """Run AppleScript, returning stdout. Raises IntegrationError on failure."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise IntegrationError(
            "The app didn't respond in time. If macOS is showing a permission "
            "prompt, approve it and retry."
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "-1743" in stderr or "not allowed" in stderr.lower():
            raise IntegrationError(
                "Confab isn't allowed to control this app. Enable it in "
                "System Settings → Privacy & Security → Automation, then retry."
            )
        raise IntegrationError(stderr[-300:] or "AppleScript failed.")
    return result.stdout.strip()


def _quote(text: str) -> str:
    """Escape a Python string into an AppleScript double-quoted literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "")
    return f'"{escaped}"'


def _as_date(var: str, when: datetime) -> str:
    """Locale-safe AppleScript that sets ``var`` to ``when``.

    ``date "..."`` literals parse per the user's locale — building the date
    from components sidesteps that entirely.
    """
    return (
        f"set {var} to current date\n"
        f"set year of {var} to {when.year}\n"
        f"set month of {var} to {when.month}\n"
        f"set day of {var} to {when.day}\n"
        f"set hours of {var} to {when.hour}\n"
        f"set minutes of {var} to {when.minute}\n"
        f"set seconds of {var} to 0\n"
    )


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise IntegrationError(f"Unusable date on this proposal: {value!r}") from exc


@dataclass
class AppleReminders:
    id: str = "apple-reminders"
    label: str = "Apple Reminders"

    def available(self) -> bool:
        return True  # ships with macOS

    def propose(self, ctx: MeetingContext) -> list[ProposalDraft]:
        return [
            ProposalDraft(
                kind="reminder",
                target=self.id,
                title=item,
                body=f"From meeting: {ctx.title}",
            )
            for item in ctx.action_items
        ]

    def apply(self, title: str, body: str, payload: dict) -> AppliedRef:
        due = ""
        if payload.get("due_iso"):
            due = _as_date("dueDate", _parse_iso(payload["due_iso"]))
        due_prop = ", due date:dueDate" if due else ""
        script = (
            'tell application "Reminders"\n'
            f"  if not (exists list {_quote(CONTAINER)}) then make new list "
            f"with properties {{name:{_quote(CONTAINER)}}}\n"
            f"  {due}"
            f"  set newReminder to make new reminder at end of reminders of "
            f"list {_quote(CONTAINER)} with properties "
            f"{{name:{_quote(title)}, body:{_quote(body)}{due_prop}}}\n"
            "  return id of newReminder\n"
            "end tell"
        )
        return AppliedRef(ref=run_osascript(script))


@dataclass
class AppleCalendar:
    id: str = "apple-calendar"
    label: str = "Apple Calendar"

    def available(self) -> bool:
        return True

    def propose(self, ctx: MeetingContext) -> list[ProposalDraft]:
        drafts = []
        for event in ctx.events:
            if not event.get("title") or not event.get("start_iso"):
                continue
            drafts.append(
                ProposalDraft(
                    kind="event",
                    target=self.id,
                    title=event["title"],
                    body=f"From meeting: {ctx.title}",
                    payload={
                        "start_iso": event["start_iso"],
                        "duration_min": int(event.get("duration_min") or 30),
                    },
                )
            )
        return drafts

    def apply(self, title: str, body: str, payload: dict) -> AppliedRef:
        start = _parse_iso(payload.get("start_iso", ""))
        end = start + timedelta(minutes=int(payload.get("duration_min") or 30))
        script = (
            'tell application "Calendar"\n'
            f"  if not (exists calendar {_quote(CONTAINER)}) then make new "
            f"calendar with properties {{name:{_quote(CONTAINER)}}}\n"
            f"  {_as_date('startDate', start)}"
            f"  {_as_date('endDate', end)}"
            f"  set newEvent to make new event at end of events of calendar "
            f"{_quote(CONTAINER)} with properties "
            f"{{summary:{_quote(title)}, description:{_quote(body)}, "
            "start date:startDate, end date:endDate}\n"
            "  return uid of newEvent\n"
            "end tell"
        )
        return AppliedRef(ref=run_osascript(script))


@dataclass
class AppleNotes:
    id: str = "apple-notes"
    label: str = "Apple Notes"

    def available(self) -> bool:
        return True

    def propose(self, ctx: MeetingContext) -> list[ProposalDraft]:
        if not ctx.summary:
            return []
        lines = [ctx.summary]
        if ctx.key_points:
            lines.append("\nKey points:")
            lines += [f"• {point}" for point in ctx.key_points]
        if ctx.decisions:
            lines.append("\nDecisions:")
            lines += [f"• {decision}" for decision in ctx.decisions]
        if ctx.action_items:
            lines.append("\nAction items:")
            lines += [f"• {item}" for item in ctx.action_items]
        return [
            ProposalDraft(
                kind="note",
                target=self.id,
                title=ctx.title,
                body="\n".join(lines),
            )
        ]

    def apply(self, title: str, body: str, payload: dict) -> AppliedRef:
        # Notes bodies are HTML; <div> per line renders like typed text.
        html_lines = "".join(
            f"<div>{_html_escape(line) or '<br>'}</div>" for line in body.split("\n")
        )
        html = f"<h1>{_html_escape(title)}</h1>{html_lines}"
        script = (
            'tell application "Notes"\n'
            f"  if not (exists folder {_quote(CONTAINER)}) then make new folder "
            f"with properties {{name:{_quote(CONTAINER)}}}\n"
            f"  set newNote to make new note at folder {_quote(CONTAINER)} "
            f"with properties {{body:{_quote(html)}}}\n"
            "  return id of newNote\n"
            "end tell"
        )
        return AppliedRef(ref=run_osascript(script))


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
