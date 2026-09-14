"""The single upstream call the hosted tier meters against (OpenAI-compatible).

Isolated + injectable so the proxy and tests never need a live key: tests
monkeypatch ``chat_completion``. The real call forwards to ONE funded provider
account — the legitimate alternative to farming free keys.
"""

from __future__ import annotations

import httpx

import config


class UpstreamError(RuntimeError):
    """Upstream provider call failed; carries an HTTP-ish status for the proxy."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def chat_completion(payload: dict) -> dict:
    """POST an OpenAI-style chat completion upstream and return the JSON.

    The response includes ``usage`` (prompt/completion/total tokens) which the
    proxy meters against the caller's monthly cap.
    """
    if not config.UPSTREAM_API_KEY:
        raise UpstreamError("Hosted tier isn't configured (no upstream key).", 503)
    body = {"model": payload.get("model") or config.UPSTREAM_MODEL, **payload}
    body.pop("stream", None)  # skeleton: non-streaming
    try:
        resp = httpx.post(
            f"{config.UPSTREAM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {config.UPSTREAM_API_KEY}"},
            json=body,
            timeout=config._TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise UpstreamError("Couldn't reach the upstream provider.", 502) from exc
    if resp.status_code != 200:
        raise UpstreamError(f"Upstream returned HTTP {resp.status_code}.", 502)
    return resp.json()
