"""Retrieval-augmented chat over a single meeting's transcript.

Retrieval is scoped to one meeting: embed the question, cosine-rank the
meeting's segments, and ground the answer on the top-k. The system prompt
forbids answering from outside that context, so replies stay sourced.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from packages.intelligence.client import OllamaClient

logger = logging.getLogger(__name__)


class EmbedderLike(Protocol):
    """Anything that turns text into unit vectors (keeps RAG decoupled from
    the storage package's concrete embedder)."""

    def encode(self, texts: list[str]) -> np.ndarray: ...
    def encode_one(self, text: str) -> np.ndarray: ...

__all__ = ["MeetingRAG", "RetrievedSegment"]


@dataclass
class RetrievedSegment:
    segment_id: int
    text: str
    score: float


_SYSTEM = (
    "You are answering questions about a meeting. Use ONLY the numbered context "
    "passages provided — do not use outside knowledge. If the answer is not in "
    "the context, say you don't know. Be concise, and cite the passages you use "
    "like [1] or [2]."
)


class MeetingRAG:
    """Question answering grounded in one meeting's transcript."""

    def __init__(self, client: OllamaClient, embedder: EmbedderLike) -> None:
        self.client = client
        self.embedder = embedder

    def retrieve(
        self,
        question: str,
        segments: list[tuple[int, str]],
        k: int = 5,
    ) -> list[RetrievedSegment]:
        """Top-``k`` meeting segments most relevant to ``question``."""
        if not segments:
            return []
        seg_vectors = self.embedder.encode([text for _, text in segments])
        query = self.embedder.encode_one(question)
        scores = seg_vectors @ query
        top = np.argsort(-scores)[:k]
        return [
            RetrievedSegment(segments[i][0], segments[i][1], float(scores[i]))
            for i in top
        ]

    def chat_stream(
        self, question: str, retrieved: list[RetrievedSegment]
    ) -> Iterator[str]:
        """Stream a grounded answer for ``question`` given ``retrieved`` context."""
        if not retrieved:
            yield "I don't have any transcript for this meeting to answer from."
            return
        context = "\n".join(
            f"[{i + 1}] {segment.text}" for i, segment in enumerate(retrieved)
        )
        prompt = f"Context passages:\n{context}\n\nQuestion: {question}"
        yield from self.client.stream(prompt, system=_SYSTEM)
