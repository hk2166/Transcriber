"""Thin Ollama wrapper — completion + streaming, with a clear offline error."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx
import ollama

from packages.intelligence.providers import LLMUnavailable

logger = logging.getLogger(__name__)

__all__ = ["OllamaClient", "OllamaUnavailable"]

#: One exception class for every provider — existing `except OllamaUnavailable`
#: sites (postprocess, chat) catch cloud failures too.
OllamaUnavailable = LLMUnavailable


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

    def _translate(self, exc: Exception) -> OllamaUnavailable:
        """Turn a low-level failure into an actionable, user-facing message.

        The ``ollama`` client talks over httpx, so an unreachable server
        surfaces as ``httpx.ConnectError`` — NOT Python's builtin
        ``ConnectionError`` — and a missing model as ``ollama.ResponseError``.
        Both must be caught for the app to degrade gracefully.
        """
        if isinstance(exc, ollama.ResponseError) and "not found" in str(exc).lower():
            return OllamaUnavailable(
                f'The model "{self.model}" isn\'t installed. '
                f"Run: ollama pull {self.model}"
            )
        return OllamaUnavailable(
            "Ollama isn't running. Open the Ollama app and try again."
        )

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
        except (ConnectionError, httpx.HTTPError, ollama.ResponseError) as exc:
            raise self._translate(exc) from exc
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
        except (ConnectionError, httpx.HTTPError, ollama.ResponseError) as exc:
            raise self._translate(exc) from exc
