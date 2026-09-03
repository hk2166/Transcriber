"""Person prep: scoped retrieval, lens structure, and 'empty is stated, never
invented' — all with injected fakes (no DB, no model)."""

from __future__ import annotations

from dataclasses import dataclass

from packages.intelligence.prep import LENSES, format_date, stream_prep


@dataclass
class Hit:
    segment_id: int
    meeting_id: int
    meeting_title: str
    text: str
    score: float


CORPUS = [
    Hit(1, 10, "Planning sync", "Sarah will send the budget by Friday", 0.9),
    Hit(2, 10, "Planning sync", "we agreed to hire two backend engineers", 0.8),
    Hit(3, 20, "Infra review", "the kubernetes deployment keeps crashing", 0.95),  # NOT her meeting
]


def scoped_retriever(query, meeting_ids, k):
    return [h for h in CORPUS if h.meeting_id in meeting_ids][:k]


class FakeClient:
    def __init__(self):
        self.calls: list[tuple[str, str | None]] = []

    def stream(self, prompt, system=None, options=None):
        self.calls.append((prompt, system))
        yield "Grounded answer "
        yield "[1]"


def _events(meeting_ids, retrieve=scoped_retriever, client=None):
    client = client or FakeClient()
    events = list(stream_prep(
        "Sarah", meeting_ids, retrieve=retrieve, client=client,
        meeting_date=lambda mid: {10: "Aug 12", 20: "Sep 1"}[mid],
    ))
    return events, client


def test_lenses_stream_in_order_and_scope_excludes_other_meetings():
    events, client = _events([10])

    lens_keys = [e.data["key"] for e in events if e.kind == "lens"]
    assert lens_keys == [lens.key for lens in LENSES]
    assert events[-1].kind == "done"
    # Every lens got sources → tokens → lens_done, in that order.
    for lens in LENSES:
        kinds = [e.kind for e in events if e.data.get("key") == lens.key]
        assert kinds == ["lens", "sources", "token", "token", "lens_done"]
    # The other meeting's passage never surfaces, in any lens.
    all_source_text = " ".join(
        s["text"] for e in events if e.kind == "sources" for s in e.data["sources"]
    )
    assert "kubernetes" not in all_source_text
    assert "budget" in all_source_text


def test_sources_carry_citation_metadata():
    events, _ = _events([10])
    source = next(e for e in events if e.kind == "sources").data["sources"][0]
    assert source["meeting_title"] == "Planning sync"
    assert source["date"] == "Aug 12"  # renders as "Planning sync · Aug 12"
    assert {"segment_id", "meeting_id", "text", "score"} <= source.keys()


def test_generation_reuses_the_grounded_cited_prompt_discipline():
    events, client = _events([10])
    prompt, system = client.calls[0]
    assert "ONLY the numbered context" in system and "[1]" in system  # MeetingRAG._SYSTEM
    assert "[1] Sarah will send the budget by Friday" in prompt        # numbered passages
    assert "Sarah" in prompt                                            # the person is named
    assert len(client.calls) == len(LENSES)


def test_empty_lens_is_stated_and_never_invented():
    events, client = _events([10], retrieve=lambda q, ids, k: [])
    assert [e.kind for e in events if e.kind in ("lens_empty", "sources")] == ["lens_empty"] * 4
    assert client.calls == []  # the model was never asked to make something up
    assert events[-1].kind == "done"


def test_no_meetings_means_all_lenses_empty_without_retrieval():
    calls = []
    events, client = _events([], retrieve=lambda q, ids, k: calls.append(q) or [])
    assert calls == [] and client.calls == []
    assert sum(e.kind == "lens_empty" for e in events) == 4


def test_format_date():
    assert format_date("2026-08-12T09:30:00") == "Aug 12"
    assert format_date(None) == "" and format_date("nope") == ""
