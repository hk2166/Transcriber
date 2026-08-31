"""Google OAuth helpers: PKCE, URL, token exchange (mocked network)."""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest

from packages.integrations import google_oauth
from packages.integrations.google_oauth import (
    GoogleAuthError,
    authorization_url,
    exchange_code,
    make_pkce,
)


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = make_pkce()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected
    assert 43 <= len(verifier) <= 128
    assert "=" not in challenge  # unpadded


def test_authorization_url_has_required_params():
    url = authorization_url("cid", "http://127.0.0.1:8765/google/callback", "chal", "st")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["cid"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["access_type"] == ["offline"]  # gets a refresh token
    assert q["prompt"] == ["consent"]
    assert "calendar.events" in q["scope"][0] and "drive.file" in q["scope"][0]


class FakeResponse:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data
        self.text = str(data)

    def json(self):
        return self._data


def test_exchange_code_returns_tokens(monkeypatch):
    monkeypatch.setattr(
        google_oauth.httpx,
        "post",
        lambda *a, **k: FakeResponse(
            200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3599}
        ),
    )
    tokens = exchange_code(
        code="c", code_verifier="v", client_id="id", client_secret="s",
        redirect_uri="http://127.0.0.1:8765/google/callback",
    )
    assert (tokens.access_token, tokens.refresh_token) == ("at", "rt")


def test_exchange_code_surfaces_google_error(monkeypatch):
    monkeypatch.setattr(
        google_oauth.httpx,
        "post",
        lambda *a, **k: FakeResponse(400, {"error_description": "invalid_grant"}),
    )
    with pytest.raises(GoogleAuthError, match="invalid_grant"):
        exchange_code(code="c", code_verifier="v", client_id="id",
                      client_secret="s", redirect_uri="http://127.0.0.1/x")
