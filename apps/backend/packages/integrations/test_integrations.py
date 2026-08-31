"""Integrations: propose drafts, AppleScript escaping, extractor validation."""

from datetime import datetime, timedelta

import pytest

from packages.integrations import apple
from packages.integrations.apple import (
    AppleCalendar,
    AppleNotes,
    AppleReminders,
    _quote,
)
from packages.integrations.base import IntegrationError, MeetingContext
from packages.integrations.extractor import _validate, extract_events

CTX = MeetingContext(
    meeting_id=1,
    title="Quarterly planning review",
    started_at="2026-08-23T14:00:00",
    summary="We agreed to freeze the build Wednesday.",
    action_items=["Freeze the build", "Draft release notes"],
    key_points=["Launch end of month"],
    decisions=["Freeze Wednesday"],
    events=[{"title": "Design review", "start_iso": "2026-08-27T14:00", "duration_min": 45}],
)


# --- propose -----------------------------------------------------------------

def test_reminders_propose_one_per_action_item():
    drafts = AppleReminders().propose(CTX)
    assert [d.title for d in drafts] == CTX.action_items
    assert all(d.kind == "reminder" for d in drafts)


def test_calendar_propose_uses_extracted_events():
    drafts = AppleCalendar().propose(CTX)
    assert len(drafts) == 1
    assert drafts[0].payload == {"start_iso": "2026-08-27T14:00", "duration_min": 45}


def test_notes_propose_bundles_summary_sections():
    (draft,) = AppleNotes().propose(CTX)
    assert "Action items:" in draft.body and "• Freeze the build" in draft.body
    assert AppleNotes().propose(
        MeetingContext(1, "t", "2026-01-01T00:00", "", [], [], [], [])
    ) == []  # no summary → nothing to file


# --- AppleScript safety --------------------------------------------------------

def test_quote_escapes_injection_attempts():
    hostile = 'end tell" & (do shell script "rm -rf ~") & "'
    quoted = _quote(hostile)
    assert quoted.startswith('"') and quoted.endswith('"')
    assert '\\"' in quoted and '" &' not in quoted.replace('\\"', "")
    assert _quote('a\\b"c\nd') == '"a\\\\b\\"c\\nd"'


def test_apply_builds_script_and_returns_ref(monkeypatch):
    scripts = []

    def fake_run(script):
        scripts.append(script)
        return "x-apple-reminderkit://REMCDReminder/abc"

    monkeypatch.setattr(apple, "run_osascript", fake_run)
    ref = AppleReminders().apply(
        'Say "hello"', "From meeting: Q3", {"due_iso": "2026-08-27T09:00"}
    )
    assert ref.ref.endswith("/abc")
    (script,) = scripts
    assert '\\"hello\\"' in script  # quotes escaped into the literal
    assert "set year of dueDate to 2026" in script  # locale-safe date build
    assert 'exists list "Confab"' in script


def test_apply_permission_denied_is_friendly(monkeypatch):
    def denied(script):
        raise IntegrationError(
            "Confab isn't allowed to control this app. Enable it in "
            "System Settings → Privacy & Security → Automation, then retry."
        )

    monkeypatch.setattr(apple, "run_osascript", denied)
    with pytest.raises(IntegrationError, match="System Settings"):
        AppleNotes().apply("t", "b", {})


# --- extractor -----------------------------------------------------------------

class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, prompt, system=None, format=None):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_extract_events_parses_and_validates():
    events = extract_events(
        FakeLLM('{"events": [{"title": "Design review", "start_iso": '
                '"2026-08-27T14:00", "duration_min": 45}]}'),
        "Q3", "summary", "transcript", "2026-08-23T14:00:00",
    )
    assert events == [
        {"title": "Design review", "start_iso": "2026-08-27T14:00", "duration_min": 45}
    ]


def test_extract_events_swallows_llm_failure():
    assert extract_events(FakeLLM(RuntimeError("down")), "t", "s", "x",
                          "2026-08-23T14:00:00") == []
    assert extract_events(FakeLLM("not json"), "t", "s", "x",
                          "2026-08-23T14:00:00") == []


def test_validate_drops_garbage_keeps_sane():
    start = datetime(2026, 8, 23, 14, 0)
    far = (start + timedelta(days=999)).isoformat()
    events = _validate(
        [
            {"title": "ok", "start_iso": "2026-08-25T10:00", "duration_min": 30},
            {"title": "", "start_iso": "2026-08-25T10:00"},          # no title
            {"title": "bad date", "start_iso": "sometime"},           # unparseable
            {"title": "too far", "start_iso": far},                   # past horizon
            "not a dict",
        ],
        start.isoformat(),
    )
    assert [e["title"] for e in events] == ["ok"]
