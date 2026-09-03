"""/people endpoints on an in-memory DB with the scoped search + LLM faked."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import llm
import routers.people as people_router
import search_index
from main import app
from packages.storage import (
    add_meeting_attendee,
    connect,
    create_meeting,
    get_segments_for_meetings,
    insert_segment,
    set_meeting_title,
    upsert_person_by_email,
)

client = TestClient(app)


class FakeClient:
    def stream(self, prompt, system=None, options=None):
        yield "Sarah owes the budget "
        yield "[1]"


@pytest.fixture
def world(monkeypatch):
    conn = connect(":memory:")
    monkeypatch.setattr(people_router, "get_db", lambda: conn)
    monkeypatch.setattr(llm, "current_client", lambda: FakeClient())

    sync = create_meeting(conn, source="both", wav_path=None,
                          started_at=datetime(2026, 8, 12, 9, 30))
    set_meeting_title(conn, sync, "Planning sync")
    other = create_meeting(conn, source="both", wav_path=None,
                           started_at=datetime(2026, 9, 1, 9, 30))
    set_meeting_title(conn, other, "Infra review")
    insert_segment(conn, sync, text="Sarah will send the budget by Friday",
                   start_ms=0, end_ms=1000, language="en", confidence=0.9)
    insert_segment(conn, other, text="the kubernetes deployment keeps crashing",
                   start_ms=0, end_ms=1000, language="en", confidence=0.9)
    sarah = upsert_person_by_email(conn, "sarah@x.com", display_name="Sarah")
    add_meeting_attendee(conn, sync, sarah)
    dana = upsert_person_by_email(conn, "dana@x.com", display_name="Dana")

    # Scoped search stand-in over the in-memory transcript.
    def fake_search_meetings(query, meeting_ids, k=10):
        return [
            SimpleNamespace(segment_id=s.id, meeting_id=s.meeting_id, text=s.text,
                            score=0.9, meeting_title="Planning sync" if s.meeting_id == sync else "Infra review")
            for s in get_segments_for_meetings(conn, list(meeting_ids))
        ][:k]
    monkeypatch.setattr(search_index, "search_meetings", fake_search_meetings)
    return SimpleNamespace(conn=conn, sync=sync, other=other, sarah=sarah, dana=dana)


def test_roster_and_detail(world):
    roster = client.get("/people").json()
    assert {p["primary_email"] for p in roster} == {"sarah@x.com", "dana@x.com"}
    sarah = next(p for p in roster if p["id"] == world.sarah)
    assert sarah["meeting_count"] == 1 and sarah["display_name"] == "Sarah"

    detail = client.get(f"/people/{world.sarah}").json()
    assert [m["title"] for m in detail["meetings"]] == ["Planning sync"]
    assert detail["person"]["notes"] == ""


def test_patch_round_trips_and_validates(world):
    r = client.patch(f"/people/{world.sarah}", json={"notes": "prefers async", "display_name": "Sarah K."})
    assert r.status_code == 200
    assert (r.json()["notes"], r.json()["display_name"]) == ("prefers async", "Sarah K.")
    assert client.get(f"/people/{world.sarah}").json()["person"]["notes"] == "prefers async"
    assert client.patch(f"/people/{world.sarah}", json={}).status_code == 422
    assert client.patch("/people/9999", json={"notes": "x"}).status_code == 404
    assert client.get("/people/9999").status_code == 404
    assert client.get("/people/9999/prep").status_code == 404


def test_merge(world):
    assert client.post("/people/merge", json={"keep_id": world.sarah, "drop_id": world.dana}).status_code == 200
    assert client.get(f"/people/{world.dana}").status_code == 404
    assert client.post("/people/merge", json={"keep_id": world.sarah, "drop_id": 9999}).status_code == 404


def test_prep_streams_four_cited_lenses_and_persists_nothing(world):
    def counts():
        return tuple(world.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("people", "transcript_segments", "summaries", "meetings"))
    before = counts()

    body = client.get(f"/people/{world.sarah}/prep").text

    assert body.count("event: lens\n") == 4
    assert body.count("event: lens_done\n") == 4
    assert body.count("event: sources\n") == 4
    assert body.strip().endswith("event: done\ndata: {}")
    assert "Planning sync" in body and '"date": "Aug 12"' in body   # citation metadata
    assert "kubernetes" not in body                                 # scoped to her meetings
    assert "Sarah owes the budget" in body                          # streamed tokens
    assert counts() == before                                       # computed view: nothing stored
