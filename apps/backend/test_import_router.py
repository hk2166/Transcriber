"""POST /audio/import — upload → decode → create meeting → schedule (mocked)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import postprocess_job
import routers.audio as audio_router
from main import app
from packages.storage import connect, get_meeting

client = TestClient(app)


@pytest.fixture
def world(monkeypatch, tmp_path):
    conn = connect(":memory:")
    monkeypatch.setattr(audio_router, "get_db", lambda: conn)
    monkeypatch.setattr(audio_router, "default_recordings_dir", lambda: tmp_path)
    scheduled: list[tuple[int, str]] = []
    monkeypatch.setattr(
        postprocess_job, "schedule_import",
        lambda meeting_id, wav_path: scheduled.append((meeting_id, wav_path)),
    )
    return SimpleNamespace(conn=conn, scheduled=scheduled)


def test_import_creates_processing_meeting_and_schedules(monkeypatch, world):
    monkeypatch.setattr(audio_router, "decode_to_wav", lambda src, dst: 12.3)
    resp = client.post(
        "/audio/import",
        files={"file": ("Team standup.mp4", b"fake-bytes", "video/mp4")},
    )
    assert resp.status_code == 200
    meeting = resp.json()
    assert meeting["source"] == "import"
    assert meeting["status"] == "processing"
    assert meeting["title"] == "Team standup"  # from the filename, sans extension
    assert meeting["wav_path"].endswith(".wav")
    # scheduled exactly once, for this meeting + its decoded wav
    assert len(world.scheduled) == 1
    assert world.scheduled[0] == (meeting["id"], meeting["wav_path"])
    # persisted
    assert get_meeting(world.conn, meeting["id"]).status == "processing"


def test_import_rejects_undecodable_file(monkeypatch, world):
    def boom(src, dst):
        raise RuntimeError("no audio stream")

    monkeypatch.setattr(audio_router, "decode_to_wav", boom)
    resp = client.post(
        "/audio/import",
        files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert resp.status_code == 400
    assert "audio or" in resp.json()["detail"]
    assert world.scheduled == []  # nothing scheduled on a bad file


def test_import_no_extension_uses_the_stem(monkeypatch, world):
    monkeypatch.setattr(audio_router, "decode_to_wav", lambda src, dst: 1.0)
    resp = client.post(
        "/audio/import", files={"file": ("voice-memo", b"x", "audio/mp4")}
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "voice-memo"
