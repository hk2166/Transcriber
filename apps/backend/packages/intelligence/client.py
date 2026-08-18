"""Thin Ollama wrapper — completion + streaming, with a clear offline error."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import ollama

logger = logging.getLogger(__name__)

__all__ = ["OllamaClient", "OllamaUnavailable"]


class OllamaUnavailable(RuntimeError):
    """Raised when the Ollama server can't be reached."""


class OllamaClient:
    """Local LLM access via Ollama.

    ``format`` may be ``"json"`` or a JSON-schema dict to constrain output.
    A missing server raises :class:`OllamaUnavailable` so callers can degrade
    gracefully (the app works transcription-only without Ollama).
    """

    def __init__(self, model: str = "llama3.2", host: str | None = None) -> None:
        self.model = model
        self._client = ollama.Client(host=host)

    def _messages(self, prompt: str, system: str | None) -> list[dict[str, str]]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        format: Any = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Return the model's full reply."""
        try:
            response = self._client.chat(
                model=self.model,
                messages=self._messages(prompt, system),
                format=format,
                options=options or {},
            )
        except ConnectionError as exc:
            raise OllamaUnavailable(
                "Ollama is not running. Start it with `ollama serve`."
            ) from exc
        return response.message.content or ""

    def stream(
        self,
        prompt: str,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        """Yield reply chunks as they are generated."""
        try:
            for chunk in self._client.chat(
                model=self.model,
                messages=self._messages(prompt, system),
                stream=True,
                options=options or {},
            ):
                piece = chunk.message.content
                if piece:
                    yield piece
        except ConnectionError as exc:
            raise OllamaUnavailable(
                "Ollama is not running. Start it with `ollama serve`."
            ) from exc
