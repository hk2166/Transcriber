"""/llm/hosted — sign in, status, sign out against a mocked gateway."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

import routers.hosted as hosted
from main import app
from settings import Settings

client = TestClient(app)


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=self)


@pytest.fixture
def env(monkeypatch):
    saved = {}
    state = {"settings": Settings(), "resolved": ""}
    monkeypatch.setattr(hosted, "get_settings", lambda: state["settings"])
    monkeypatch.setattr(hosted, "save_settings", lambda s: saved.update(api_keys=dict(s.api_keys)))
    monkeypatch.setattr(hosted, "resolve_api_key", lambda s, provider: state["resolved"])
    monkeypatch.setattr(hosted.keychain, "delete_secret", lambda *a: None)
    return type("Env", (), {"saved": saved, "state": state})


ACCOUNT = {"email": "a@b.com", "remaining": 800, "token_limit": 1000, "tokens_used": 200}


def test_signin_stores_token_and_returns_quota(monkeypatch, env):
    monkeypatch.setattr(hosted.httpx, "post", lambda *a, **k: FakeResp(200, {"token": "cfb_tok"}))
    monkeypatch.setattr(hosted.httpx, "get", lambda *a, **k: FakeResp(200, ACCOUNT))
    r = client.post("/llm/hosted/signin", json={"email": "a@b.com"}).json()
    assert r == {"signed_in": True, "email": "a@b.com", "remaining": 800,
                 "token_limit": 1000, "tokens_used": 200}
    assert env.saved["api_keys"]["confab-hosted"] == "cfb_tok"  # token persisted


def test_signin_gateway_down_is_502(monkeypatch, env):
    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(hosted.httpx, "post", boom)
    r = client.post("/llm/hosted/signin", json={"email": "a@b.com"})
    assert r.status_code == 502 and "hosted service" in r.json()["detail"]


def test_status_signed_out_and_in(monkeypatch, env):
    assert client.get("/llm/hosted/status").json() == {"signed_in": False}
    env.state["resolved"] = "cfb_tok"
    monkeypatch.setattr(hosted.httpx, "get", lambda *a, **k: FakeResp(200, ACCOUNT))
    r = client.get("/llm/hosted/status").json()
    assert r["signed_in"] is True and r["remaining"] == 800 and r["email"] == "a@b.com"


def test_status_signed_in_but_gateway_unreachable(monkeypatch, env):
    env.state["resolved"] = "cfb_tok"
    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(hosted.httpx, "get", boom)
    r = client.get("/llm/hosted/status").json()
    assert r["signed_in"] is True and "error" in r


def test_signout_clears(monkeypatch, env):
    env.state["settings"] = Settings(api_keys={"confab-hosted": "keychain"})
    assert client.post("/llm/hosted/signout").json() == {"signed_in": False}
    assert "confab-hosted" not in env.saved["api_keys"]
