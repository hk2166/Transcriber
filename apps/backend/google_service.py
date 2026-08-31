"""Google connection: keychain-stored credentials + the connect/callback dance.

Secrets (the OAuth client secret and the refresh token) go in the macOS
Keychain via the built-in ``security`` CLI — no dependency, and off-disk. A
Keychain failure falls back to the existing chmod-600 settings store so the
feature still works headless.

The loopback redirect is a route on the sidecar's own localhost server, so no
extra server and no pre-registered port (Google's loopback flow allows any
127.0.0.1 port).
"""

from __future__ import annotations

import logging
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any

from packages.integrations import google_oauth
from packages.integrations.google_oauth import GoogleAuthError
from settings import get_settings, save_settings

logger = logging.getLogger(__name__)

__all__ = [
    "GoogleAuthError",
    "access_token",
    "begin_connect",
    "complete_callback",
    "disconnect",
    "save_client",
    "setup_plan",
    "status",
]

_SERVICE = "com.hemant.confab.google"
_lock = threading.Lock()

#: Pending consent flows keyed by OAuth ``state`` (short-lived, in memory).
_pending: dict[str, dict[str, Any]] = {}
_PENDING_TTL = 600  # seconds


# --- Keychain (with settings fallback) ---------------------------------------

def _keychain_set(account: str, value: str) -> bool:
    try:
        subprocess.run(
            ["security", "add-generic-password", "-U", "-s", _SERVICE,
             "-a", account, "-w", value],
            capture_output=True, check=True, timeout=10,
        )
        return True
    except Exception:
        return False


def _keychain_get(account: str) -> str | None:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", _SERVICE, "-a", account, "-w"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def _keychain_delete(account: str) -> None:
    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", _SERVICE, "-a", account],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass


def _store(account: str, value: str) -> None:
    if not _keychain_set(account, value):
        # Fallback: chmod-600 settings store (same place API keys live).
        s = get_settings()
        keys = dict(s.api_keys)
        keys[f"_google_{account}"] = value
        save_settings(s.model_copy(update={"api_keys": keys}))


def _load(account: str) -> str | None:
    value = _keychain_get(account)
    if value is not None:
        return value
    return get_settings().api_keys.get(f"_google_{account}")


def _clear(account: str) -> None:
    _keychain_delete(account)
    s = get_settings()
    if f"_google_{account}" in s.api_keys:
        keys = dict(s.api_keys)
        keys.pop(f"_google_{account}", None)
        save_settings(s.model_copy(update={"api_keys": keys}))


# --- Setup guidance (gcloud script + console deep-links) ----------------------

@dataclass
class SetupPlan:
    gcloud_available: bool
    script: str
    links: list[dict[str, str]]


def setup_plan() -> SetupPlan:
    """The one-time project setup: a gcloud script + deep-links to the console.

    The scriptable parts (create project, enable APIs) use Google's OWN CLI.
    Creating the OAuth client has no supported API — it's the single manual
    console step, deep-linked so there's nothing to navigate.
    """
    gcloud = _has_gcloud()
    project = f"confab-{secrets.token_hex(3)}"
    script = (
        "#!/usr/bin/env bash\n"
        "# Run once. Creates a Google Cloud project and turns on the APIs\n"
        "# Confab needs. You'll be asked to sign in (Google's own gcloud flow).\n"
        "set -e\n"
        "gcloud auth login\n"
        f'gcloud projects create {project} --name="Confab"\n'
        f"gcloud config set project {project}\n"
        "gcloud services enable calendar-json.googleapis.com "
        "docs.googleapis.com drive.googleapis.com\n"
        f'echo "✓ Project {project} ready. Now create the OAuth client '
        'in the console page Confab opens, and paste the two values back."\n'
    )
    links = [
        {
            "label": "1 · Configure the consent screen (External, add your email as a test user)",
            "url": "https://console.cloud.google.com/auth/overview",
        },
        {
            "label": "2 · Create OAuth client → Application type: Desktop app",
            "url": "https://console.cloud.google.com/auth/clients/create",
        },
    ]
    return SetupPlan(gcloud_available=gcloud, script=script, links=links)


def _has_gcloud() -> bool:
    try:
        subprocess.run(["gcloud", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


# --- Credentials + connection state ------------------------------------------

def save_client(client_id: str, client_secret: str) -> None:
    """Store the pasted OAuth client id/secret."""
    with _lock:
        _store("client_id", client_id.strip())
        _store("client_secret", client_secret.strip())


def _client() -> tuple[str, str] | None:
    cid = _load("client_id")
    secret = _load("client_secret")
    return (cid, secret) if cid and secret else None


def status() -> dict[str, Any]:
    """Connection state for the UI."""
    return {
        "has_client": _client() is not None,
        "connected": _load("refresh_token") is not None,
        "email": _load("email") or None,
    }


def begin_connect(redirect_base: str) -> str:
    """Start the consent flow; returns the auth URL for the browser to open.

    ``redirect_base`` is the frontend's own origin (a 127.0.0.1 loopback) so
    the callback lands back on this sidecar.
    """
    client = _client()
    if client is None:
        raise GoogleAuthError("Add your Google client ID and secret first.")
    if not (redirect_base.startswith("http://127.0.0.1")
            or redirect_base.startswith("http://localhost")):
        raise GoogleAuthError("Refusing a non-loopback redirect.")

    client_id, _ = client
    verifier, challenge = google_oauth.make_pkce()
    state = secrets.token_urlsafe(24)
    redirect_uri = f"{redirect_base.rstrip('/')}/google/callback"

    with _lock:
        _prune_pending()
        _pending[state] = {
            "verifier": verifier,
            "redirect_uri": redirect_uri,
            "created": time.monotonic(),
        }
    return google_oauth.authorization_url(client_id, redirect_uri, challenge, state)


def complete_callback(state: str, code: str) -> str:
    """Loopback handler: exchange the code, store the refresh token, name the
    account. Returns the connected email."""
    with _lock:
        pending = _pending.pop(state, None)
    if pending is None:
        raise GoogleAuthError("This sign-in link expired — start again from Confab.")
    client = _client()
    if client is None:
        raise GoogleAuthError("Google client credentials are missing.")
    client_id, client_secret = client

    tokens = google_oauth.exchange_code(
        code=code,
        code_verifier=pending["verifier"],
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=pending["redirect_uri"],
    )
    if not tokens.refresh_token:
        raise GoogleAuthError(
            "Google didn't return a refresh token — remove Confab's access at "
            "myaccount.google.com/permissions and connect again."
        )
    email = google_oauth.userinfo_email(tokens.access_token)
    with _lock:
        _store("refresh_token", tokens.refresh_token)
        if email:
            _store("email", email)
    logger.info("Google connected (%s).", email or "unknown account")
    return email


def disconnect() -> None:
    with _lock:
        for account in ("refresh_token", "email"):
            _clear(account)


def access_token() -> str:
    """A valid access token for API calls (refreshes on demand). Blocking."""
    client = _client()
    refresh = _load("refresh_token")
    if client is None or refresh is None:
        raise GoogleAuthError("Google isn't connected.")
    client_id, client_secret = client
    tokens = google_oauth.refresh_access_token(
        refresh_token=refresh, client_id=client_id, client_secret=client_secret
    )
    return tokens.access_token


def _prune_pending() -> None:
    now = time.monotonic()
    for state in [s for s, p in _pending.items() if now - p["created"] > _PENDING_TTL]:
        _pending.pop(state, None)
