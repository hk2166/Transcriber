"""Wires integrations to the app: propose after a meeting, apply on approval.

The privacy contract lives here (docs/INTEGRATIONS.md): ``propose_for_meeting``
is local-only (DB + LLM extraction), and ``apply_proposal`` is the ONLY code
path that sends meeting content anywhere — called exclusively by the apply
endpoints the user clicks.
"""

from __future__ import annotations

import logging

import llm
from database import get_db
from packages.integrations import (
    INTEGRATIONS,
    IntegrationError,
    MeetingContext,
    get_integration,
)
from packages.integrations.extractor import extract_events
from packages.storage import (
    Proposal,
    get_meeting,
    get_proposals,
    get_segments,
    get_summary,
    insert_proposals,
    mark_proposals_stale,
    set_proposal_result,
)
from settings import get_settings

logger = logging.getLogger(__name__)

__all__ = ["apply_proposal", "enabled_integrations", "propose_for_meeting"]


def enabled_integrations() -> list:
    """Integrations that are available and not turned off in Settings."""
    toggles = get_settings().integrations_enabled
    return [
        integration
        for integration in INTEGRATIONS
        if integration.available() and toggles.get(integration.id, True)
    ]


def _build_context(meeting_id: int) -> MeetingContext | None:
    db = get_db()
    meeting = get_meeting(db, meeting_id)
    summary = get_summary(db, meeting_id)
    if meeting is None or summary is None:
        return None  # nothing worth proposing without a summary
    return MeetingContext(
        meeting_id=meeting_id,
        title=meeting.title,
        started_at=meeting.started_at,
        summary=summary.summary,
        action_items=summary.action_items,
        key_points=summary.key_points,
        decisions=summary.decisions,
    )


def propose_for_meeting(meeting_id: int) -> int:
    """Generate proposals (local only). Returns how many were created.

    Blocking (LLM call) — run via ``asyncio.to_thread``. Any failure is the
    caller's to swallow: proposing must never block a meeting reaching ready.
    """
    ctx = _build_context(meeting_id)
    if ctx is None:
        return 0

    targets = enabled_integrations()
    if not targets:
        return 0

    # Calendar extraction only if the calendar target is on (it's the only
    # consumer, and the only part that needs the LLM).
    if any(t.id == "apple-calendar" for t in targets):
        transcript_tail = "\n".join(
            s.text for s in get_segments(get_db(), meeting_id)[-40:]
        )
        try:
            client = llm.current_client()
            ctx.events = extract_events(
                client, ctx.title, ctx.summary, transcript_tail, ctx.started_at
            )
        except Exception:
            logger.info("No LLM for event extraction — calendar proposals skipped.")

    drafts = []
    for integration in targets:
        try:
            drafts += integration.propose(ctx)
        except Exception:
            logger.exception("propose() failed for %s", integration.id)

    db = get_db()
    mark_proposals_stale(db, meeting_id)
    if drafts:
        insert_proposals(
            db,
            meeting_id,
            [(d.kind, d.target, d.title, d.body, d.payload) for d in drafts],
        )
    logger.info("Proposed %d sync items for meeting %d.", len(drafts), meeting_id)
    return len(drafts)


def apply_proposal(proposal: Proposal) -> Proposal:
    """Execute one user-approved proposal; records the outcome. Blocking."""
    db = get_db()
    if proposal.status == "applied":
        return proposal  # idempotent: double-click returns the existing ref
    integration = get_integration(proposal.target)
    if integration is None:
        set_proposal_result(
            db, proposal.id, status="failed", error="Unknown integration."
        )
    else:
        try:
            ref = integration.apply(proposal.title, proposal.body, proposal.payload)
            set_proposal_result(
                db, proposal.id, status="applied", external_ref=ref.ref, error=None
            )
        except IntegrationError as exc:
            set_proposal_result(db, proposal.id, status="failed", error=str(exc))
        except Exception:
            logger.exception("apply failed for proposal %d", proposal.id)
            set_proposal_result(
                db,
                proposal.id,
                status="failed",
                error="Something went wrong applying this item.",
            )
    refreshed = [p for p in get_proposals(db, proposal.meeting_id) if p.id == proposal.id]
    return refreshed[0] if refreshed else proposal
