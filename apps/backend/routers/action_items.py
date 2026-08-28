"""Cross-meeting action items: list everything, toggle done."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db
from packages.storage import ActionItem, get_action_items, set_action_item_done

router = APIRouter(tags=["action-items"])


@router.get("/action-items")
def list_action_items() -> list[ActionItem]:
    """Every meeting's action items, newest meeting first."""
    return get_action_items(get_db())


class DonePatch(BaseModel):
    done: bool


@router.patch("/action-items/{item_id}")
def patch_action_item(item_id: int, patch: DonePatch) -> dict[str, bool]:
    """Check or un-check one action item."""
    if not set_action_item_done(get_db(), item_id, patch.done):
        raise HTTPException(status_code=404, detail=f"Action item {item_id} not found.")
    return {"updated": True}
