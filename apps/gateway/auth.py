"""FastAPI auth dependencies: the caller's user token, and the admin token."""

from __future__ import annotations

import sqlite3

from fastapi import Depends, Header, HTTPException

import config
import store
from db import get_db


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    return authorization[7:].strip()


def current_user(
    authorization: str | None = Header(default=None),
) -> sqlite3.Row:
    """Resolve the user from their API token, or 401."""
    token = _bearer(authorization)
    user = store.user_by_token(get_db(), token)
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown or revoked token.")
    return user


def require_admin(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> None:
    """Guard the /admin surface with the shared admin token (header either way)."""
    token = x_admin_token or (authorization[7:].strip() if authorization else "")
    if not token or token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token required.")


AdminDep = Depends(require_admin)
UserDep = Depends(current_user)
