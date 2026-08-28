"""OllamaClient error translation — the graceful-degradation contract.

The ollama client talks over httpx, so an unreachable server raises
``httpx.ConnectError`` (NOT builtin ConnectionError) and a missing model
raises ``ollama.ResponseError``. Both must become ``OllamaUnavailable`` with an
actionable message, or the app's AI features fail with a raw stack trace.
"""

import httpx
import ollama
import pytest

from packages.intelligence import OllamaClient, OllamaUnavailable


def test_connect_error_becomes_ollama_unavailable(monkeypatch):
    client = OllamaClient()

    def refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(client._client, "chat", refuse)

    with pytest.raises(OllamaUnavailable, match="Ollama isn't running"):
        client.complete("hi")
    with pytest.raises(OllamaUnavailable, match="Ollama isn't running"):
        list(client.stream("hi"))


def test_missing_model_gives_pull_hint(monkeypatch):
    client = OllamaClient(model="ghost")

    def not_found(*args, **kwargs):
        raise ollama.ResponseError("model 'ghost' not found, try pulling it first")

    monkeypatch.setattr(client._client, "chat", not_found)

    with pytest.raises(OllamaUnavailable, match="ollama pull ghost"):
        client.complete("hi")
