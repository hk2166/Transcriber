"""RAG tests — real embedder for retrieval, fake client for grounding/stream."""

import pytest

from packages.intelligence.rag import MeetingRAG, RetrievedSegment

SEGMENTS = [
    (1, "The database migration is complete and ahead of schedule."),
    (2, "We are under budget by fifteen percent this quarter."),
    (3, "Let's decide the launch date next week after the beta feedback."),
    (4, "Can you draft the job description by Friday?"),
]


class FakeClient:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.last_prompt: str | None = None
        self.last_system: str | None = None

    def stream(self, prompt, system=None, options=None):
        self.last_prompt = prompt
        self.last_system = system
        yield from self.chunks


@pytest.fixture(scope="module")
def embedder():
    from packages.storage.embedder import Embedder

    return Embedder()


def test_retrieve_ranks_relevant_segment_first(embedder):
    rag = MeetingRAG(FakeClient([]), embedder)
    hits = rag.retrieve("when are we launching?", SEGMENTS, k=2)
    assert hits[0].segment_id == 3  # the launch-date line
    assert hits[0].score >= hits[1].score


def test_retrieve_caps_at_k(embedder):
    rag = MeetingRAG(FakeClient([]), embedder)
    assert len(rag.retrieve("budget", SEGMENTS, k=2)) == 2


def test_chat_stream_grounds_prompt_and_streams():
    client = FakeClient(["We ", "decided ", "next week."])
    rag = MeetingRAG(client, embedder=None)  # retrieval not used here
    retrieved = [RetrievedSegment(3, SEGMENTS[2][1], 0.7)]
    out = "".join(rag.chat_stream("when?", retrieved))
    assert out == "We decided next week."
    assert "launch date next week" in client.last_prompt
    assert "ONLY" in client.last_system


def test_chat_stream_without_context_declines():
    client = FakeClient(["should not be used"])
    rag = MeetingRAG(client, embedder=None)
    out = "".join(rag.chat_stream("anything?", []))
    assert "don't have" in out.lower()
    assert client.last_prompt is None  # model never called
