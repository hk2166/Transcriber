"""Sign-up / identity for the downloaded desktop app.

Skeleton: email → API token, no verification yet. Harden with a magic-link or
OAuth (the desktop app already has the Google loopback pattern to reuse) before
this is public — that's noted in the README.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import store
from auth import UserDep
from db import get_db

router = APIRouter(tags=["auth"])


class RegisterRequest(BaseModel):
    email: str


@router.post("/auth/register")
def register(body: RegisterRequest) -> dict:
    """Create/get the user for this email and return a fresh API token (once)."""
    email = body.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return store.create_user(get_db(), email)


@router.get("/auth/me")
def me(user=UserDep) -> dict:
    """The caller's account + remaining free-tier tokens this month."""
    return store.account(get_db(), user)
