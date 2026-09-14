"""Confab Hosted tier: sign in to the opt-in gateway and check remaining quota.

Local-first stays the default. This only manages the token for users who pick
the "Confab Hosted" LLM provider; the token is stored like any other provider
key (Keychain sentinel) and the OpenAI-compatible client routes through the
gateway automatically.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import keychain
from packages.intelligence.providers import HOSTED_GATEWAY
from settings import (
    LLM_KEYCHAIN_SERVICE,
    get_settings,
    resolve_api_key,
    save_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm/hosted", tags=["hosted"])

_PROVIDER = "confab-hosted"
_TIMEOUT = 20


def _account(token: str) -> dict:
    """Fetch the signed-in account + remaining quota from the gateway."""
    resp = httpx.get(
        f"{HOSTED_GATEWAY}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _status_payload(token: str) -> dict:
    account = _account(token)
    return {
        "signed_in": True,
        "email": account.get("email"),
        "remaining": account.get("remaining"),
        "token_limit": account.get("token_limit"),
        "tokens_used": account.get("tokens_used"),
    }


class SignInRequest(BaseModel):
    email: str


@router.post("/signin")
def signin(body: SignInRequest) -> dict:
    """Register/sign in with an email and store the returned hosted token."""
    try:
        resp = httpx.post(
            f"{HOSTED_GATEWAY}/auth/register", json={"email": body.email}, timeout=_TIMEOUT
        )
        resp.raise_for_status()
        token = resp.json()["token"]
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="Couldn't reach Confab's hosted service."
        ) from exc

    settings = get_settings()
    keys = dict(settings.api_keys)
    keys[_PROVIDER] = token
    save_settings(settings.model_copy(update={"api_keys": keys}))

    try:
        return _status_payload(token)
    except httpx.HTTPError:
        return {"signed_in": True, "email": body.email.strip().lower()}


@router.get("/status")
def status() -> dict:
    """Whether the hosted tier is signed in, and this month's remaining tokens."""
    token = resolve_api_key(get_settings(), _PROVIDER)
    if not token:
        return {"signed_in": False}
    try:
        return _status_payload(token)
    except httpx.HTTPError:
        return {"signed_in": True, "email": None, "error": "Couldn't reach the hosted service."}


@router.post("/signout")
def signout() -> dict:
    """Forget the hosted token (local only; the account keeps existing)."""
    settings = get_settings()
    if _PROVIDER in settings.api_keys:
        keys = dict(settings.api_keys)
        keys.pop(_PROVIDER, None)
        save_settings(settings.model_copy(update={"api_keys": keys}))
    keychain.delete_secret(LLM_KEYCHAIN_SERVICE, _PROVIDER)
    return {"signed_in": False}
