"""Speaker endpoints: rename."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db
from packages.storage import rename_speaker

router = APIRouter(prefix="/speakers", tags=["speakers"])


class RenameRequest(BaseModel):
    speaker_id: int
    name: str


@router.post("/rename")
def rename(request: RenameRequest) -> dict[str, bool]:
    """Set a speaker's display name; 404 if the speaker is unknown."""
    if not rename_speaker(get_db(), request.speaker_id, request.name):
        raise HTTPException(
            status_code=404, detail=f"Speaker {request.speaker_id} not found."
        )
    return {"renamed": True}
