"""Local-LLM intelligence for MeetingMind (Ollama): summaries, titles, chat."""

from packages.intelligence.client import OllamaClient, OllamaUnavailable
from packages.intelligence.rag import MeetingRAG, RetrievedSegment
from packages.intelligence.summarizer import (
    MeetingSummary,
    generate_title,
    summarize,
)

__all__ = [
    "MeetingRAG",
    "MeetingSummary",
    "OllamaClient",
    "OllamaUnavailable",
    "RetrievedSegment",
    "generate_title",
    "summarize",
]
