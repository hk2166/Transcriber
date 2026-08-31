"""Google OAuth 2.0 for a desktop app — loopback + PKCE (the only sanctioned
installed-app flow; the copy/paste "OOB" flow is dead).

Pure helpers: PKCE, the consent URL, and token exchange/refresh over httpx.
No app state, no storage — those live in ``google_service``. The user brings
their OWN OAuth client (their Google Cloud project), so Confab is never a
data-collecting middleman and needs no Google app verification.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

__all__ = [
    "SCOPES",
    "GoogleAuthError",
    "TokenSet",
    "authorization_url",
    "exchange_code",
    "make_pkce",
    "refresh_access_token",
    "userinfo_email",
]

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

#: Minimal scopes: identify the user, create events, and create Docs the app
#: owns. drive.file is NON-sensitive (files this app created only), which keeps
#: verification light; calendar.events is the one sensitive scope.
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.file",
]

_TIMEOUT = 20


class GoogleAuthError(RuntimeError):
    """OAuth exchange failed; the message is user-facing."""


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_in: int


def make_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` per RFC 7636 (S256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(
    client_id: str, redirect_uri: str, code_challenge: str, state: str
) -> str:
    """Build the consent URL the system browser opens."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",  # ask for a refresh token
        "prompt": "consent",  # force it even on re-consent
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def _post_token(data: dict) -> dict:
    try:
        response = httpx.post(TOKEN_ENDPOINT, data=data, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise GoogleAuthError("Couldn't reach Google to exchange the code.") from exc
    if response.status_code != 200:
        detail = ""
        try:
            body = response.json()
            detail = body.get("error_description") or body.get("error") or ""
        except Exception:
            detail = response.text[:200]
        raise GoogleAuthError(f"Google rejected the request: {detail}")
    return response.json()


def exchange_code(
    *, code: str, code_verifier: str, client_id: str, client_secret: str,
    redirect_uri: str,
) -> TokenSet:
    """Trade the authorization code for tokens."""
    body = _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }
    )
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_in=int(body.get("expires_in", 3600)),
    )


def refresh_access_token(
    *, refresh_token: str, client_id: str, client_secret: str
) -> TokenSet:
    """Mint a fresh access token from the stored refresh token."""
    body = _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token", refresh_token),
        expires_in=int(body.get("expires_in", 3600)),
    )


def userinfo_email(access_token: str) -> str:
    """The connected account's email — proves the token works, names the account."""
    try:
        response = httpx.get(
            USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("email", "")
    except httpx.HTTPError:
        return ""
