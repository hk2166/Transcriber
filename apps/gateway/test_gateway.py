"""Gateway: registration, metered proxy, free-tier cap, admin controls (mocked upstream)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
import db
import providers
from main import app

client = TestClient(app)

ADMIN = {"X-Admin-Token": config.ADMIN_TOKEN}


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    db._conn = db.connect(":memory:")
    monkeypatch.setattr(config, "DEFAULT_TOKEN_LIMIT", 1000)
    # Deterministic upstream: every call "costs" 100 prompt + 20 completion tokens.
    monkeypatch.setattr(
        providers, "chat_completion",
        lambda payload: {
            "model": payload.get("model") or "gpt-4o-mini",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        },
    )
    yield
    db.close_db()


def _register(email="a@b.com"):
    r = client.post("/auth/register", json={"email": email})
    assert r.status_code == 200
    return r.json()["token"]


def _complete(token):
    return client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )


# --- auth / identity ---------------------------------------------------------------

def test_register_issues_token_and_me_reports_quota():
    token = _register("Me@Example.com ")
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["email"] == "me@example.com"  # normalised
    assert me["tokens_used"] == 0 and me["token_limit"] == 1000 and me["remaining"] == 1000


def test_unknown_token_is_401():
    assert _complete("cfb_nonsense").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer x"}).status_code == 401


# --- metered proxy -----------------------------------------------------------------

def test_proxy_meters_usage():
    token = _register()
    assert _complete(token).status_code == 200
    assert _complete(token).status_code == 200
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["tokens_used"] == 240 and me["remaining"] == 760  # 2 × 120


def test_free_tier_cap_blocks_further_calls():
    token = _register()
    # limit 1000, 120/call → 9th call crosses the cap
    for _ in range(9):
        assert _complete(token).status_code == 200
    blocked = _complete(token)
    assert blocked.status_code == 402 and "Free tier" in blocked.json()["detail"]


def test_blocked_user_is_forbidden(monkeypatch):
    token = _register()
    users = client.get("/admin/users", headers=ADMIN).json()
    client.patch(f"/admin/users/{users[0]['id']}", headers=ADMIN, json={"status": "blocked"})
    assert _complete(token).status_code == 403


# --- admin -------------------------------------------------------------------------

def test_admin_requires_token():
    assert client.get("/admin/users").status_code == 403
    assert client.get("/admin/users", headers={"X-Admin-Token": "wrong"}).status_code == 403
    assert client.get("/admin/users", headers=ADMIN).status_code == 200


def test_admin_can_raise_limit_and_reset_usage():
    token = _register()
    _complete(token)
    uid = client.get("/admin/users", headers=ADMIN).json()[0]["id"]

    bumped = client.patch(f"/admin/users/{uid}", headers=ADMIN, json={"token_limit": 5000}).json()
    assert bumped["token_limit"] == 5000

    client.post(f"/admin/users/{uid}/reset", headers=ADMIN)
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["tokens_used"] == 0

    assert client.patch("/admin/users/9999", headers=ADMIN, json={"status": "blocked"}).status_code == 404


def test_monthly_period_rolls_the_used_count():
    import store
    token = _register()
    _complete(token)
    conn = db.get_db()
    # Simulate a stale period: pretend the used-count is from an earlier month.
    conn.execute("UPDATE users SET period = '2000-01', tokens_used = 999")
    conn.commit()
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["tokens_used"] == 0 and me["period"] == store.current_period()
