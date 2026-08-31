"""Google connection state machine — mocked keychain + network."""

import pytest

import google_service
from packages.integrations import google_oauth
from packages.integrations.google_oauth import GoogleAuthError, TokenSet


@pytest.fixture(autouse=True)
def in_memory_keychain(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(google_service, "_keychain_set",
                        lambda a, v: (store.__setitem__(a, v), True)[1])
    monkeypatch.setattr(google_service, "_keychain_get", lambda a: store.get(a))
    monkeypatch.setattr(google_service, "_keychain_delete", lambda a: store.pop(a, None))
    google_service._pending.clear()
    yield store


def test_status_progresses_client_then_connected():
    assert google_service.status() == {"has_client": False, "connected": False, "email": None}
    google_service.save_client("cid", "secret")
    assert google_service.status()["has_client"] is True
    assert google_service.status()["connected"] is False


def test_begin_connect_requires_client_and_loopback():
    with pytest.raises(GoogleAuthError, match="client"):
        google_service.begin_connect("http://127.0.0.1:8765")
    google_service.save_client("cid", "secret")
    with pytest.raises(GoogleAuthError, match="loopback"):
        google_service.begin_connect("https://evil.example.com")
    url = google_service.begin_connect("http://127.0.0.1:8765")
    assert url.startswith("https://accounts.google.com/") and "cid" in url
    assert len(google_service._pending) == 1  # state stashed


def test_full_connect_stores_refresh_token(monkeypatch):
    google_service.save_client("cid", "secret")
    google_service.begin_connect("http://127.0.0.1:8765")
    state = next(iter(google_service._pending))
    monkeypatch.setattr(google_oauth, "exchange_code",
                        lambda **k: TokenSet("at", "rt", 3600))
    monkeypatch.setattr(google_oauth, "userinfo_email", lambda t: "me@example.com")

    email = google_service.complete_callback(state, "authcode")
    assert email == "me@example.com"
    status = google_service.status()
    assert status["connected"] is True and status["email"] == "me@example.com"


def test_callback_rejects_unknown_state():
    with pytest.raises(GoogleAuthError, match="expired"):
        google_service.complete_callback("nope", "code")


def test_missing_refresh_token_is_actionable(monkeypatch):
    google_service.save_client("cid", "secret")
    google_service.begin_connect("http://127.0.0.1:8765")
    state = next(iter(google_service._pending))
    monkeypatch.setattr(google_oauth, "exchange_code",
                        lambda **k: TokenSet("at", None, 3600))  # no refresh token
    with pytest.raises(GoogleAuthError, match="permissions"):
        google_service.complete_callback(state, "code")


def test_disconnect_clears(monkeypatch):
    google_service.save_client("cid", "secret")
    google_service.begin_connect("http://127.0.0.1:8765")
    state = next(iter(google_service._pending))
    monkeypatch.setattr(google_oauth, "exchange_code",
                        lambda **k: TokenSet("at", "rt", 3600))
    monkeypatch.setattr(google_oauth, "userinfo_email", lambda t: "me@example.com")
    google_service.complete_callback(state, "code")
    google_service.disconnect()
    assert google_service.status()["connected"] is False


def test_setup_plan_scripts_project_and_apis():
    plan = google_service.setup_plan()
    assert "gcloud projects create confab-" in plan.script
    assert "calendar-json.googleapis.com" in plan.script
    assert any("Desktop app" in link["label"] for link in plan.links)
