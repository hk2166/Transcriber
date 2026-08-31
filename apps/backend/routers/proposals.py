"""Sync proposals: review, edit, skip, and — only on explicit approval — apply."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import proposal_service
from database import get_db
from packages.integrations import INTEGRATIONS
from packages.storage import (
    Proposal,
    get_meeting,
    get_proposal,
    get_proposals,
    set_proposal_status,
    update_proposal,
)
from settings import get_settings

router = APIRouter(tags=["proposals"])


@router.get("/integrations")
def list_integrations() -> list[dict]:
    """Registry for Settings: what exists, what's available, what's enabled."""
    toggles = get_settings().integrations_enabled
    return [
        {
            "id": integration.id,
            "label": integration.label,
            "available": integration.available(),
            "enabled": toggles.get(integration.id, True),
        }
        for integration in INTEGRATIONS
    ]


@router.get("/meetings/{meeting_id}/proposals")
def meeting_proposals(meeting_id: int) -> list[Proposal]:
    if get_meeting(get_db(), meeting_id) is None:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found.")
    return get_proposals(get_db(), meeting_id)


class ProposalPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    payload: dict | None = None
    status: Literal["proposed", "skipped"] | None = None


@router.patch("/proposals/{proposal_id}")
def patch_proposal(proposal_id: int, patch: ProposalPatch) -> Proposal:
    """Edit a card, or move it between proposed ↔ skipped. Never applies."""
    db = get_db()
    if get_proposal(db, proposal_id) is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    if patch.title is not None or patch.body is not None or patch.payload is not None:
        update_proposal(
            db, proposal_id, title=patch.title, body=patch.body, payload=patch.payload
        )
    if patch.status is not None:
        set_proposal_status(db, proposal_id, patch.status)
    return get_proposal(db, proposal_id)


@router.post("/proposals/{proposal_id}/apply")
async def apply_one(proposal_id: int) -> Proposal:
    """The consent moment: clicking Apply IS the approval."""
    proposal = get_proposal(get_db(), proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    if proposal.status in ("skipped", "stale"):
        raise HTTPException(status_code=409, detail="This proposal isn't active.")
    return await asyncio.to_thread(proposal_service.apply_proposal, proposal)


@router.post("/meetings/{meeting_id}/proposals/apply")
async def apply_all(meeting_id: int) -> list[Proposal]:
    """Apply every open proposal on the meeting; per-item results."""
    db = get_db()
    if get_meeting(db, meeting_id) is None:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found.")
    open_items = [p for p in get_proposals(db, meeting_id) if p.status in ("proposed", "failed")]
    for proposal in open_items:
        await asyncio.to_thread(proposal_service.apply_proposal, proposal)
    return get_proposals(db, meeting_id)
