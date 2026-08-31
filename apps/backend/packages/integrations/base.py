"""The integration contract: propose drafts, apply approved proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = [
    "AppliedRef",
    "Integration",
    "IntegrationError",
    "MeetingContext",
    "ProposalDraft",
]


class IntegrationError(RuntimeError):
    """Apply failed; the message is user-facing (shown on the proposal card)."""


@dataclass
class MeetingContext:
    """Everything an integration may propose from — assembled once per meeting."""

    meeting_id: int
    title: str
    started_at: str  # ISO, meeting-local
    summary: str
    action_items: list[str]
    key_points: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    #: LLM-extracted follow-ups: {"title", "start_iso", "duration_min"}.
    events: list[dict] = field(default_factory=list)


@dataclass
class ProposalDraft:
    kind: str  # reminder | event | note | page
    target: str  # integration id
    title: str
    body: str = ""
    payload: dict = field(default_factory=dict)


@dataclass
class AppliedRef:
    """What the target returned: a stable id and, when available, a URL."""

    ref: str
    url: str | None = None


@runtime_checkable
class Integration(Protocol):
    id: str
    label: str

    def available(self) -> bool:
        """Target reachable (app installed / token configured)."""
        ...

    def propose(self, ctx: MeetingContext) -> list[ProposalDraft]:
        """Local-only drafts; never performs I/O with meeting content."""
        ...

    def apply(self, title: str, body: str, payload: dict) -> AppliedRef:
        """Execute one user-approved proposal. Raises IntegrationError."""
        ...
