"""LLM intelligence for Confab: summaries, titles, chat.

Local (Ollama) by default; optional cloud providers via API key — all behind
the same complete()/stream() interface (see providers.py).
"""

from packages.intelligence.client import OllamaClient, OllamaUnavailable
from packages.intelligence.providers import (
    PROVIDERS,
    LLMUnavailable,
    ProviderSpec,
    make_client,
)
from packages.intelligence.rag import MeetingRAG, RetrievedSegment
from packages.intelligence.summarizer import (
    MeetingSummary,
    generate_title,
    summarize,
)

__all__ = [
    "LLMUnavailable",
    "MeetingRAG",
    "MeetingSummary",
    "OllamaClient",
    "OllamaUnavailable",
    "PROVIDERS",
    "ProviderSpec",
    "RetrievedSegment",
    "generate_title",
    "make_client",
    "summarize",
]
