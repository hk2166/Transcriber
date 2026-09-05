"""Sync proposals: review, edit, skip, and — only on explicit approval — apply.

Also the integrations registry the Settings UI reads, and the Notion
connection test — a read-only check that sends no meeting content.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import proposal_service
from database import get_db
from packages.integrations import INTEGRATIONS, IntegrationError, notion
from packages.storage import (
    Proposal,
    get_meeting,
    get_proposal,
    get_proposals,
    set_proposal_status,
    update_proposal,
)
from settings import Settings, get_settings, resolve_api_key

router = APIRouter(tags=["proposals"])


@router.get("/integrations")
def list_integrations() -> list[dict]:
    """Registry for Settings: what exists, what's available/enabled, what needs
    setup. ``configured`` mirrors ``available()``; ``hint`` explains an
    unconfigured target (only Notion needs a token today)."""
    toggles = get_settings().integrations_enabled
    rows = []
    for integration in INTEGRATIONS:
        available = integration.available()
        hint = None if available or integration.id != "notion" else notion.SETUP_HINT
        rows.append(
            {
                "id": integration.id,
                "label": integration.label,
                "available": available,
                "enabled": toggles.get(integration.id, True),
                "needs_token": integration.needs_token,
                "configured": available,
                "hint": hint,
            }
        )
    return rows


@router.post("/integrations/notion/test")
async def test_notion(candidate: Settings) -> dict:
    """Validate an unsaved Notion token + parent before Save. No meeting content
    leaves: this only identifies the bot and resolves the parent."""
    token = resolve_api_key(candidate, "notion")
    parent = candidate.notion_parent
    if not token.strip() or not parent.strip():
        return {"ok": False, "error": notion.SETUP_HINT}
    try:
        info = await asyncio.to_thread(notion.whoami, token)
        resolved = await asyncio.to_thread(notion.resolve_parent, token, parent)
    except IntegrationError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "bot_name": info["bot_name"],
        "workspace_name": info["workspace_name"],
        "parent": {"kind": resolved.kind, "title": resolved.title},
    }


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
