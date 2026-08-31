"""Provider layer: factory selection, error translation, JSON fence handling."""

import httpx
import pytest

from packages.intelligence import LLMUnavailable, make_client
from packages.intelligence.client import OllamaClient
from packages.intelligence.providers import (
    AnthropicClient,
    OpenAICompatClient,
    _strip_fences,
)


def test_factory_selects_the_right_client():
    assert isinstance(make_client("ollama"), OllamaClient)
    assert isinstance(make_client("openai", api_key="sk-x"), OpenAICompatClient)
    assert isinstance(make_client("groq", api_key="k"), OpenAICompatClient)
    assert isinstance(make_client("anthropic", api_key="k"), AnthropicClient)


def test_factory_guards():
    with pytest.raises(LLMUnavailable, match="Unknown LLM provider"):
        make_client("nope")
    with pytest.raises(LLMUnavailable, match="no API key"):
        make_client("openai")
    with pytest.raises(LLMUnavailable, match="no server URL"):
        make_client("custom")


def test_default_and_explicit_models():
    assert make_client("openai", api_key="k").model == "gpt-5-mini"
    assert make_client("openai", model="gpt-5", api_key="k").model == "gpt-5"


def test_strip_fences():
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_fences('{"a": 1}') == '{"a": 1}'


def _openai_client_with_response(handler) -> OpenAICompatClient:
    client = make_client("openai", api_key="sk-test")
    transport = httpx.MockTransport(handler)
    # Route the provider's httpx.Client through the mock transport.
    original_init = httpx.Client.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    return client, patched, original_init


def test_openai_error_translation(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    client, patched, original = _openai_client_with_response(handler)
    monkeypatch.setattr(httpx.Client, "__init__", patched)
    with pytest.raises(LLMUnavailable, match="API key was rejected"):
        client.complete("hi")


def test_openai_complete_parses_choices(monkeypatch):
    def handler(request):
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello there"}}]},
        )

    client, patched, original = _openai_client_with_response(handler)
    monkeypatch.setattr(httpx.Client, "__init__", patched)
    assert client.complete("hi") == "hello there"
