"""On-demand person prep — a computed view, never persisted.

Before you meet someone, answer four fixed questions ("lenses") about them
from the transcripts of meetings they attended. Retrieval runs over the
persisted, meeting-scoped vector index (no re-embedding); generation reuses
:class:`~packages.intelligence.rag.MeetingRAG` verbatim, so every answer is
grounded in numbered passages and cites them as ``[n]``. Nothing produced
here is written to the database — each request recomputes from evidence.

Dependencies (the retriever, the LLM client, meeting metadata) are injected
so the generator is pure and unit-testable without a database or a model.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from packages.intelligence.rag import LLMLike, MeetingRAG, RetrievedSegment

__all__ = ["LENSES", "Lens", "PrepEvent", "PrepSource", "format_date", "stream_prep"]


@dataclass(frozen=True)
class Lens:
    key: str
    title: str
    retrieval_query: str  # what we search the person's meetings for
    instruction: str  # the grounded question the LLM answers ({name} filled in)


LENSES: tuple[Lens, ...] = (
    # The passages handed to the model come ONLY from meetings this person
    # attended (retrieval is scoped by meeting id), so each instruction says so:
    # transcripts rarely name an attendee, and the model must not demand it.
    Lens(
        "open_commitments",
        "Open commitments",
        "action items, promises, deadlines involving this person",
        "The passages are from meetings that {name} attended. List the open "
        "commitments, promises, and deadlines discussed in them: who owes what, "
        "and by when. Be brief and concrete.",
    ),
    Lens(
        "recent_decisions",
        "Recent decisions",
        "decisions made, agreements reached, conclusions",
        "The passages are from meetings that {name} attended. Summarise the "
        "decisions and agreements reached in them.",
    ),
    Lens(
        "open_questions",
        "Open questions",
        "unresolved questions, pending answers, follow-ups",
        "The passages are from meetings that {name} attended. List the questions "
        "or follow-ups that were left open in them.",
    ),
    Lens(
        "recurring_context",
        "Recurring context",
        "topics, projects, concerns that come up repeatedly",
        "The passages are from meetings that {name} attended. What themes, "
        "projects, or concerns come up repeatedly across them?",
    ),
)


class Hit(Protocol):
    """A scoped-search hit (search_index.SearchResult, or a test stand-in)."""

    segment_id: int
    meeting_id: int
    meeting_title: str
    text: str
    score: float


#: ``(query, meeting_ids, k) -> hits`` — the meeting-scoped search.
Retriever = Callable[[str, set[int], int], Sequence[Hit]]
#: ``meeting_id -> "Aug 12"`` — so a citation can read "Planning sync · Aug 12".
MeetingDate = Callable[[int], str]


@dataclass
class PrepSource:
    segment_id: int
    meeting_id: int
    meeting_title: str
    date: str
    text: str
    score: float


@dataclass
class PrepEvent:
    """One streamed step: lens | sources | token | lens_empty | lens_done | done."""

    kind: str
    data: dict


def format_date(iso: str | None) -> str:
    """``2026-08-12T09:30:00`` → ``Aug 12`` (empty if unparseable)."""
    if not iso:
        return ""
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    return f"{moment.strftime('%b')} {moment.day}"


def stream_prep(
    person_name: str,
    meeting_ids: Sequence[int],
    *,
    retrieve: Retriever,
    client: LLMLike,
    meeting_date: MeetingDate,
    k: int = 6,
) -> Iterator[PrepEvent]:
    """Yield the prep briefing for one person, lens by lens.

    Per lens: ``lens`` → ``sources`` → ``token``… → ``lens_done``; a lens with
    no relevant passages yields ``lens_empty`` instead and never calls the
    model — an empty lens is stated, not invented. Ends with ``done``.
    """
    scope = set(meeting_ids)
    # Generation only: retrieval is the scoped index, so no embedder is needed.
    rag = MeetingRAG(client, embedder=None)  # type: ignore[arg-type]
    for lens in LENSES:
        yield PrepEvent("lens", {"key": lens.key, "title": lens.title})
        hits = list(retrieve(lens.retrieval_query, scope, k)) if scope else []
        if not hits:
            yield PrepEvent("lens_empty", {"key": lens.key})
            continue
        sources = [
            PrepSource(
                segment_id=hit.segment_id,
                meeting_id=hit.meeting_id,
                meeting_title=hit.meeting_title,
                date=meeting_date(hit.meeting_id),
                text=hit.text,
                score=round(float(hit.score), 3),
            )
            for hit in hits
        ]
        yield PrepEvent(
            "sources", {"key": lens.key, "sources": [asdict(s) for s in sources]}
        )
        retrieved = [RetrievedSegment(h.segment_id, h.text, float(h.score)) for h in hits]
        question = lens.instruction.format(name=person_name)
        for token in rag.chat_stream(question, retrieved):
            yield PrepEvent("token", {"key": lens.key, "text": token})
        yield PrepEvent("lens_done", {"key": lens.key})
    yield PrepEvent("done", {})
