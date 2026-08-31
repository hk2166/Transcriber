"""Startup reconciliation of meetings a crash / force-quit left mid-flight.

``reconcile_interrupted_meetings`` must bring every meeting stuck in
``recording`` / ``processing`` to a usable terminal state, so nothing hangs
forever after an interrupted run.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

import postprocess_job
from packages.storage import (
    connect,
    create_meeting,
    get_meeting,
    insert_segment,
    set_meeting_status,
)

FIXTURE_WAV = "tests/e2e/fixtures/two_speaker_meeting.wav"


@pytest.fixture
def db(monkeypatch):
    conn = connect(":memory:")
    monkeypatch.setattr(postprocess_job, "get_db", lambda: conn)
    yield conn
    conn.close()


@pytest.fixture
def scheduled(monkeypatch):
    """Capture schedule() calls instead of spawning real post-processing."""
    calls: list[tuple[int, str]] = []
    monkeypatch.setattr(postprocess_job, "schedule", lambda mid, path: calls.append((mid, path)))
    return calls


def _meeting(conn, *, wav, status):
    mid = create_meeting(conn, source="both", wav_path=wav, started_at=datetime.now())
    set_meeting_status(conn, mid, status)
    return mid


def test_stuck_meeting_without_audio_is_unhung(db, scheduled):
    # 'recording' with no wav / no segments — nothing to finish, just unhang it.
    a = _meeting(db, wav=None, status="recording")
    # 'processing' pointing at a missing file — likewise unrecoverable.
    b = _meeting(db, wav="/no/such/file.wav", status="processing")

    postprocess_job.reconcile_interrupted_meetings()

    assert get_meeting(db, a).status == "ready"
    assert get_meeting(db, b).status == "ready"
    assert scheduled == []  # nothing to re-run


def test_recoverable_meeting_resumes_postprocessing(db, scheduled):
    assert os.path.exists(FIXTURE_WAV), "fixture recording missing"
    m = _meeting(db, wav=FIXTURE_WAV, status="processing")
    insert_segment(db, m, text="rough live text", start_ms=0, end_ms=1000,
                   language="en", confidence=0.4)

    postprocess_job.reconcile_interrupted_meetings()

    # Left in 'processing' while it re-runs, and post-processing was scheduled.
    assert get_meeting(db, m).status == "processing"
    assert scheduled == [(m, FIXTURE_WAV)]


def test_ready_meetings_are_left_alone(db, scheduled):
    done = _meeting(db, wav=FIXTURE_WAV, status="ready")

    postprocess_job.reconcile_interrupted_meetings()

    assert get_meeting(db, done).status == "ready"
    assert scheduled == []  # untouched — not stuck
