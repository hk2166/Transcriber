"""Admin API behind the admin token: see users + usage, manage access + caps."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import store
from auth import AdminDep
from db import get_db

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[AdminDep])


@router.get("/users")
def users() -> list[dict]:
    return store.list_users(get_db())


class UserPatch(BaseModel):
    token_limit: int | None = None
    status: str | None = None  # active | blocked


@router.patch("/users/{user_id}")
def patch_user(user_id: int, patch: UserPatch) -> dict:
    db = get_db()
    changed = False
    if patch.token_limit is not None:
        changed |= store.set_limit(db, user_id, patch.token_limit)
    if patch.status in ("active", "blocked"):
        changed |= (store.unblock if patch.status == "active" else store.block)(db, user_id)
    if not changed:
        raise HTTPException(status_code=404, detail="User not found or nothing to change.")
    row = next((u for u in store.list_users(db) if u["id"] == user_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return row


@router.post("/users/{user_id}/reset")
def reset_user(user_id: int) -> dict:
    if not store.reset_usage(get_db(), user_id):
        raise HTTPException(status_code=404, detail="User not found.")
    return {"reset": True, "user_id": user_id}
