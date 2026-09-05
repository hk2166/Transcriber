"""/integrations + /proposals endpoints on an in-memory DB (house TestClient pattern)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import proposal_service
import routers.proposals as proposals_router
from main import app
from packages.integrations import AppliedRef, notion
from packages.integrations.base import IntegrationError
from packages.integrations.notion import NotionAPIError, ResolvedParent
from packages.storage import (
    connect,
    create_meeting,
    get_proposals,
    insert_proposals,
    mark_proposals_stale,
    set_meeting_title,
    set_proposal_result,
    set_proposal_status,
)
from settings import Settings

client = TestClient(app)

PARENT_URL = "https://www.notion.so/Notes-" + "1" * 32


class OkIntegration:
    def apply(self, title, body, payload):
        return AppliedRef("ref-1")


class BoomIntegration:
    def apply(self, title, body, payload):
        raise IntegrationError("boom")


@pytest.fixture
def world(monkeypatch):
    conn = connect(":memory:")
    monkeypatch.setattr(proposals_router, "get_db", lambda: conn)
    monkeypatch.setattr(proposal_service, "get_db", lambda: conn)
    meeting_id = create_meeting(
        conn, source="both", wav_path=None, started_at=datetime(2026, 8, 23, 14, 0)
    )
    set_meeting_title(conn, meeting_id, "Quarterly planning review")
    return SimpleNamespace(conn=conn, meeting_id=meeting_id)


def use_settings(monkeypatch, **kwargs) -> Settings:
    """Point both modules at one Settings instance (no settings.json, no Keychain)."""
    settings = Settings(**kwargs)
    monkeypatch.setattr(proposals_router, "get_settings", lambda: settings)
    monkeypatch.setattr(proposal_service, "get_settings", lambda: settings)
    return settings


def _seed(conn, meeting_id, drafts):
    insert_proposals(conn, meeting_id, drafts)
    return get_proposals(conn, meeting_id)


# --- GET /integrations --------------------------------------------------------------

def test_registry_lists_four_targets_notion_unconfigured(monkeypatch, world):
    use_settings(monkeypatch)
    rows = client.get("/integrations").json()
    assert [r["id"] for r in rows] == [
        "apple-reminders", "apple-calendar", "apple-notes", "notion",
    ]
    apple = rows[0]
    assert apple["needs_token"] is False and apple["configured"] is True and apple["hint"] is None
    notion_row = rows[-1]
    assert notion_row["needs_token"] is True
    assert notion_row["configured"] is False
    assert notion_row["hint"] == notion.SETUP_HINT


def test_registry_reports_notion_configured(monkeypatch, world):
    use_settings(monkeypatch, api_keys={"notion": "ntn_x"}, notion_parent=PARENT_URL)
    notion_row = client.get("/integrations").json()[-1]
    assert notion_row["configured"] is True and notion_row["hint"] is None


# --- PATCH /proposals/{id} ----------------------------------------------------------

def test_patch_edits_skips_and_locks_applied(monkeypatch, world):
    use_settings(monkeypatch)
    (proposal,) = _seed(world.conn, world.meeting_id, [("note", "apple-notes", "T", "B", {})])
    edited = client.patch(f"/proposals/{proposal.id}", json={"title": "New", "body": "NB"}).json()
    assert (edited["title"], edited["body"]) == ("New", "NB")
    assert client.patch(f"/proposals/{proposal.id}", json={"status": "skipped"}).json()["status"] == "skipped"
    assert client.patch(f"/proposals/{proposal.id}", json={"status": "proposed"}).json()["status"] == "proposed"

    set_proposal_result(world.conn, proposal.id, status="applied", external_ref="x")
    locked = client.patch(f"/proposals/{proposal.id}", json={"title": "Nope"}).json()
    assert locked["title"] == "New" and locked["status"] == "applied"  # applied refuses edits
    assert client.patch("/proposals/9999", json={"title": "x"}).status_code == 404


# --- POST /proposals/{id}/apply -----------------------------------------------------

def test_apply_one_records_ref(monkeypatch, world):
    use_settings(monkeypatch)
    (proposal,) = _seed(world.conn, world.meeting_id, [("note", "apple-notes", "T", "B", {})])
    monkeypatch.setattr(proposal_service, "get_integration", lambda target: OkIntegration())
    result = client.post(f"/proposals/{proposal.id}/apply").json()
    assert result["status"] == "applied" and result["external_ref"] == "ref-1"


def test_apply_one_failure_then_inactive_conflicts(monkeypatch, world):
    use_settings(monkeypatch)
    first, second = _seed(
        world.conn, world.meeting_id,
        [("note", "apple-notes", "A", "B", {}), ("note", "apple-notes", "C", "D", {})],
    )
    monkeypatch.setattr(proposal_service, "get_integration", lambda target: BoomIntegration())
    failed = client.post(f"/proposals/{first.id}/apply").json()
    assert failed["status"] == "failed" and failed["error"] == "boom"

    set_proposal_status(world.conn, second.id, "skipped")
    assert client.post(f"/proposals/{second.id}/apply").status_code == 409  # skipped

    mark_proposals_stale(world.conn, world.meeting_id)
    assert client.post(f"/proposals/{first.id}/apply").status_code == 409  # now stale
    assert client.post("/proposals/9999/apply").status_code == 404


def test_apply_all_isolates_per_item(monkeypatch, world):
    use_settings(monkeypatch)
    _seed(
        world.conn, world.meeting_id,
        [("note", "boom-target", "A", "B", {}), ("note", "ok-target", "C", "D", {})],
    )
    monkeypatch.setattr(
        proposal_service,
        "get_integration",
        lambda target: BoomIntegration() if target == "boom-target" else OkIntegration(),
    )
    by_target = {
        p["target"]: p
        for p in client.post(f"/meetings/{world.meeting_id}/proposals/apply").json()
    }
    assert by_target["boom-target"]["status"] == "failed"
    assert by_target["ok-target"]["status"] == "applied"
    assert by_target["ok-target"]["external_ref"] == "ref-1"


# --- POST /integrations/notion/test -------------------------------------------------

def test_notion_test_names_the_parent(monkeypatch, world):
    use_settings(monkeypatch)
    monkeypatch.setattr(notion, "whoami", lambda token: {"bot_name": "Confab", "workspace_name": "Acme"})
    monkeypatch.setattr(
        notion, "resolve_parent",
        lambda token, parent: ResolvedParent("data_source", "ds-1", "Meetings", "Name"),
    )
    result = client.post(
        "/integrations/notion/test",
        json={"api_keys": {"notion": "ntn_x"}, "notion_parent": PARENT_URL},
    ).json()
    assert result == {
        "ok": True,
        "bot_name": "Confab",
        "workspace_name": "Acme",
        "parent": {"kind": "data_source", "title": "Meetings"},
    }


def test_notion_test_surfaces_a_bad_token(monkeypatch, world):
    use_settings(monkeypatch)

    def raise_401(token):
        raise NotionAPIError(
            "Notion rejected the token. Paste a fresh installation token in Settings → Notion.",
            401, "unauthorized",
        )

    monkeypatch.setattr(notion, "whoami", raise_401)
    monkeypatch.setattr(notion, "resolve_parent", lambda token, parent: None)
    result = client.post(
        "/integrations/notion/test",
        json={"api_keys": {"notion": "ntn_x"}, "notion_parent": PARENT_URL},
    ).json()
    assert result["ok"] is False and "rejected the token" in result["error"]


def test_notion_test_needs_token_and_parent(monkeypatch, world):
    use_settings(monkeypatch)
    result = client.post(
        "/integrations/notion/test", json={"api_keys": {}, "notion_parent": ""}
    ).json()
    assert result == {"ok": False, "error": notion.SETUP_HINT}
