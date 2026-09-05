"""Cross-app sync for Confab — propose → approve → apply.

Nothing here sends anything on its own: integrations *propose* drafts after a
meeting, and ``apply`` runs only for a specific proposal the user approved in
the UI (docs/INTEGRATIONS.md). App-level wiring (DB, settings, LLM) lives in
``proposal_service`` — this package stays dependency-free.
"""

from packages.integrations.apple import (
    AppleCalendar,
    AppleNotes,
    AppleReminders,
)
from packages.integrations.base import (
    AppliedRef,
    Integration,
    IntegrationError,
    MeetingContext,
    ProposalDraft,
)
from packages.integrations.notion import Notion, NotionCredentials

#: The one Notion instance; proposal_service injects its credentials provider.
NOTION = Notion()

#: Registry, in the order the UI shows them.
INTEGRATIONS: list[Integration] = [
    AppleReminders(),
    AppleCalendar(),
    AppleNotes(),
    NOTION,
]

INTEGRATIONS_BY_ID = {integration.id: integration for integration in INTEGRATIONS}


def get_integration(integration_id: str) -> Integration | None:
    return INTEGRATIONS_BY_ID.get(integration_id)


__all__ = [
    "AppleCalendar",
    "AppleNotes",
    "AppleReminders",
    "AppliedRef",
    "INTEGRATIONS",
    "INTEGRATIONS_BY_ID",
    "Integration",
    "IntegrationError",
    "MeetingContext",
    "NOTION",
    "Notion",
    "NotionCredentials",
    "ProposalDraft",
    "get_integration",
]
