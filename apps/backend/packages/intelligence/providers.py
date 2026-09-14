"""Cloud LLM providers for summaries & chat — behind the same two-method
interface as OllamaClient (``complete`` / ``stream``), so the rest of the app
doesn't know which brand of model is talking.

Two wire protocols cover the whole market:
- OpenAI-compatible chat completions (OpenAI, Gemini, Groq, Mistral, xAI,
  DeepSeek, OpenRouter, and any custom/local server like LM Studio)
- Anthropic's /v1/messages

Privacy note: using any of these sends transcript text to that provider.
Ollama stays the default; the UI labels the trade-off.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "LLMUnavailable",
    "HOSTED_GATEWAY",
    "PROVIDERS",
    "ProviderSpec",
    "make_client",
]


class LLMUnavailable(RuntimeError):
    """The configured LLM can't serve requests (offline, bad key, bad model)."""


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    base_url: str  # OpenAI-compatible /v1 root, or Anthropic API root
    default_model: str
    protocol: str  # "openai" | "anthropic" | "ollama"
    key_url: str = ""  # where users create an API key
    needs_key: bool = True


#: Root of the opt-in hosted gateway (dev default; set for real deployments).
HOSTED_GATEWAY = os.environ.get("CONFAB_HOSTED_URL", "http://127.0.0.1:8900").rstrip("/")

PROVIDERS: list[ProviderSpec] = [
    ProviderSpec(
        id="ollama",
        label="Local (Ollama)",
        base_url="",
        default_model="llama3.2",
        protocol="ollama",
        needs_key=False,
    ),
    ProviderSpec(
        id="confab-hosted",
        label="Confab Hosted (free tier)",
        base_url=f"{HOSTED_GATEWAY}/v1",
        default_model="",  # the gateway picks the upstream model
        protocol="openai",  # the gateway speaks OpenAI chat-completions
        needs_key=True,     # the "key" is the signed-in hosted token
    ),
    ProviderSpec(
        id="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-5-mini",
        protocol="openai",
        key_url="https://platform.openai.com/api-keys",
    ),
    ProviderSpec(
        id="anthropic",
        label="Anthropic (Claude)",
        base_url="https://api.anthropic.com",
        default_model="claude-haiku-4-5",
        protocol="anthropic",
        key_url="https://console.anthropic.com/settings/keys",
    ),
    ProviderSpec(
        id="gemini",
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-2.5-flash",
        protocol="openai",
        key_url="https://aistudio.google.com/apikey",
    ),
    ProviderSpec(
        id="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        protocol="openai",
        key_url="https://console.groq.com/keys",
    ),
    ProviderSpec(
        id="mistral",
        label="Mistral",
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-small-latest",
        protocol="openai",
        key_url="https://console.mistral.ai/api-keys",
    ),
    ProviderSpec(
        id="xai",
        label="xAI (Grok)",
        base_url="https://api.x.ai/v1",
        default_model="grok-4-fast-non-reasoning",
        protocol="openai",
        key_url="https://console.x.ai",
    ),
    ProviderSpec(
        id="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        protocol="openai",
        key_url="https://platform.deepseek.com/api_keys",
    ),
    ProviderSpec(
        id="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="openrouter/auto",
        protocol="openai",
        key_url="https://openrouter.ai/keys",
    ),
    ProviderSpec(
        id="custom",
        label="Custom (OpenAI-compatible)",
        base_url="",  # user-supplied (LM Studio, llama.cpp, vLLM, a proxy…)
        default_model="",
        protocol="openai",
        needs_key=False,
    ),
]

PROVIDERS_BY_ID = {spec.id: spec for spec in PROVIDERS}

_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)


def _strip_fences(text: str) -> str:
    """Cloud models often wrap JSON in ```json fences — unwrap for validation."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1] if "\n" in stripped else ""
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    return stripped.strip()


def _friendly_http_error(provider_label: str, exc: Exception) -> LLMUnavailable:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return LLMUnavailable(
                f"{provider_label}: the API key was rejected. "
                "Check it in Settings."
            )
        if code == 404:
            return LLMUnavailable(
                f"{provider_label}: unknown model. Check the model name in Settings."
            )
        if code == 429:
            return LLMUnavailable(
                f"{provider_label}: rate limit or quota exceeded. Try again shortly."
            )
        detail = ""
        try:
            body = exc.response.json()
            detail = (
                body.get("error", {}).get("message")
                or body.get("detail")  # FastAPI (the hosted gateway) shape
                or ""
            )
        except Exception:
            pass
        if code == 402:  # hosted free tier used up
            return LLMUnavailable(
                detail or f"{provider_label}: free tier used up for this month."
            )
        return LLMUnavailable(
            f"{provider_label}: request failed ({code}). {detail}".strip()
        )
    if isinstance(exc, httpx.HTTPError):
        return LLMUnavailable(
            f"{provider_label}: couldn't reach the API. Check your connection."
        )
    return LLMUnavailable(f"{provider_label}: {exc}")


class OpenAICompatClient:
    """Chat-completions client for every OpenAI-compatible provider."""

    def __init__(
        self, spec: ProviderSpec, model: str, api_key: str, base_url: str = ""
    ) -> None:
        self.spec = spec
        self.model = model or spec.default_model
        self.base_url = (base_url or spec.base_url).rstrip("/")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if spec.id == "openrouter":
            # OpenRouter likes to know who's calling (shown on their dashboard).
            headers["HTTP-Referer"] = "https://github.com/hk2166/Transcriber"
            headers["X-Title"] = "Confab"
        self._headers = headers

    def _messages(self, prompt: str, system: str | None) -> list[dict[str, str]]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _payload(
        self, prompt: str, system: str | None, format: Any, stream: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(prompt, system),
            "stream": stream,
        }
        if format is not None:
            # A JSON schema or "json" was requested. json_object is the widely
            # supported form; the prompt already says "return JSON".
            payload["response_format"] = {"type": "json_object"}
        return payload

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        format: Any = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = self._payload(prompt, system, format, stream=False)
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.post(url, json=payload, headers=self._headers)
                if response.status_code == 400 and format is not None:
                    # Some servers reject response_format — retry without it.
                    payload.pop("response_format", None)
                    response = client.post(url, json=payload, headers=self._headers)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:  # noqa: BLE001 - translated for the UI
            raise _friendly_http_error(self.spec.label, exc) from exc
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise LLMUnavailable(
                f"{self.spec.label}: unexpected response shape."
            ) from exc
        return _strip_fences(text) if format is not None else text

    def stream(
        self,
        prompt: str,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        url = f"{self.base_url}/chat/completions"
        payload = self._payload(prompt, system, None, stream=True)
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                with client.stream(
                    "POST", url, json=payload, headers=self._headers
                ) as response:
                    if response.status_code >= 400:
                        response.read()
                        response.raise_for_status()
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            delta = json.loads(chunk)["choices"][0]["delta"]
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                        piece = delta.get("content")
                        if piece:
                            yield piece
        except LLMUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - translated for the UI
            raise _friendly_http_error(self.spec.label, exc) from exc


class AnthropicClient:
    """Anthropic /v1/messages client (system is top-level, SSE for streaming)."""

    MAX_TOKENS = 4096

    def __init__(self, spec: ProviderSpec, model: str, api_key: str) -> None:
        self.spec = spec
        self.model = model or spec.default_model
        self.base_url = spec.base_url.rstrip("/")
        self._headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

    def _payload(
        self, prompt: str, system: str | None, stream: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }
        if system:
            payload["system"] = system
        return payload

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        format: Any = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        if format is not None:
            prompt += "\n\nRespond with ONLY the JSON object — no prose, no fences."
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.post(
                    f"{self.base_url}/v1/messages",
                    json=self._payload(prompt, system, stream=False),
                    headers=self._headers,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:  # noqa: BLE001 - translated for the UI
            raise _friendly_http_error(self.spec.label, exc) from exc
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        return _strip_fences(text) if format is not None else text

    def stream(
        self,
        prompt: str,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/v1/messages",
                    json=self._payload(prompt, system, stream=True),
                    headers=self._headers,
                ) as response:
                    if response.status_code >= 400:
                        response.read()
                        response.raise_for_status()
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") == "content_block_delta":
                            piece = event.get("delta", {}).get("text")
                            if piece:
                                yield piece
        except LLMUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - translated for the UI
            raise _friendly_http_error(self.spec.label, exc) from exc


def make_client(
    provider_id: str,
    model: str = "",
    api_key: str = "",
    base_url: str = "",
):
    """Build the right client for a provider id (Ollama included)."""
    spec = PROVIDERS_BY_ID.get(provider_id)
    if spec is None:
        raise LLMUnavailable(f"Unknown LLM provider: {provider_id!r}.")
    if spec.protocol == "ollama":
        from packages.intelligence.client import OllamaClient

        return OllamaClient(model=model or spec.default_model)
    if spec.needs_key and not api_key:
        raise LLMUnavailable(
            f"{spec.label}: no API key set. Add one in Settings."
        )
    if spec.id == "custom" and not base_url:
        raise LLMUnavailable(
            "Custom provider: no server URL set. Add one in Settings."
        )
    if spec.protocol == "anthropic":
        return AnthropicClient(spec, model, api_key)
    return OpenAICompatClient(spec, model, api_key, base_url=base_url)
