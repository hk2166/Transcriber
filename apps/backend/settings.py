"""User settings — persisted to ``app_data/settings.json``.

A tiny cached JSON store. Some fields take effect immediately (VAD, default
source, auto-summarise, Ollama model), while changing the Whisper model needs a
restart because the transcriber is loaded once (noted in the UI).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from typing import Literal

from pydantic import BaseModel

import keychain
from packages.audio import default_recordings_dir

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cached: Settings | None = None

#: Keychain service that holds LLM provider API keys (account = provider id).
LLM_KEYCHAIN_SERVICE = "com.hemant.confab.llm"
#: What settings.json stores in place of a key that lives in the Keychain.
KEY_SENTINEL = "keychain"


class Settings(BaseModel):
    #: Transcription engine: "whisper-base|small|medium" or "parakeet-v2|v3".
    transcription_engine: str = "whisper-small"
    whisper_model: str = "small"  # legacy; superseded by transcription_engine
    ollama_model: str = "llama3.2"
    vad_threshold: float = 0.5
    default_source: str = "both"
    auto_summarize: bool = True
    #: After a meeting ends, re-transcribe the whole recording for a cleaner,
    #: better-punctuated transcript that then gets diarized (the live transcript
    #: shows during the meeting; this supersedes it once processing finishes).
    refine_transcript: bool = True
    #: Whisper model size for that refine pass ("base|small|medium|large-v3").
    #: Bigger = more accurate but slower; the big win is full-file context +
    #: beam search even at the same size as the live engine.
    refine_model: str = "small"
    #: What to do when a meeting app (Zoom/Webex) starts a call:
    #: "off" = ignore, "prompt" = offer to record, "auto" = start recording.
    auto_record: Literal["off", "prompt", "auto"] = "prompt"
    #: Per-integration toggles for sync proposals, e.g. {"apple-notes": false}.
    #: Missing key = enabled: proposing is local-only, and nothing is ever
    #: sent without a per-item approval (docs/INTEGRATIONS.md).
    integrations_enabled: dict[str, bool] = {}
    #: Which LLM powers summaries/titles/chat. "ollama" keeps everything
    #: on-device; any other provider sends transcript text to that API.
    llm_provider: str = "ollama"
    #: Cloud model id; empty = the provider's default.
    llm_model: str = ""
    #: Server URL for the "custom" (OpenAI-compatible) provider.
    llm_base_url: str = ""
    #: Per-provider API keys. Real values live in the macOS Keychain
    #: (LLM_KEYCHAIN_SERVICE, account = provider id); settings.json holds only
    #: the KEY_SENTINEL marker. A raw value here is the graceful fallback for
    #: when the Keychain refuses (headless/locked) — plus the ``_google_*``
    #: entries google_service uses for the same reason. Resolve real values
    #: through :func:`resolve_api_key`, never by reading this dict directly.
    api_keys: dict[str, str] = {}


def _path() -> Path:
    return default_recordings_dir().parent / "settings.json"


def get_settings() -> Settings:
    global _cached
    with _lock:
        if _cached is None:
            path = _path()
            if path.exists():
                try:
                    import json

                    data = json.loads(path.read_text())
                    # Migrate pre-Parakeet settings: promote the old whisper_model
                    # choice into the new engine field.
                    if "transcription_engine" not in data and data.get("whisper_model"):
                        data["transcription_engine"] = f"whisper-{data['whisper_model']}"
                    _cached = Settings.model_validate(data)
                    # One-time: move any plaintext API keys into the Keychain.
                    _cached = _migrate_plaintext_keys(_cached, path)
                except Exception:
                    logger.exception("Bad settings.json — using defaults.")
                    _cached = Settings()
            else:
                _cached = Settings()
    return _cached


def save_settings(new: Settings) -> Settings:
    global _cached
    with _lock:
        existing = dict(_cached.api_keys) if _cached is not None else {}
        new = new.model_copy(
            update={"api_keys": _secure_api_keys(dict(new.api_keys), existing)}
        )
        path = _path()
        path.write_text(new.model_dump_json(indent=2))
        path.chmod(0o600)  # fallback entries may hold raw keys — owner-only
        _cached = new
    redacted = new.model_dump()
    redacted["api_keys"] = {k: "•••" for k in redacted.get("api_keys", {})}
    logger.info("Settings saved: %s", redacted)
    return _cached


def _secure_api_keys(
    incoming: dict[str, str], existing: dict[str, str]
) -> dict[str, str]:
    """What actually gets persisted for ``api_keys`` on save.

    A raw value is pushed into the Keychain and replaced by the sentinel (kept
    raw only if the Keychain refuses — the graceful fallback). The sentinel or
    a blank field means "unchanged": the stored value is preserved, so the
    UI's GET→edit→PUT round-trip (which only ever sees sentinels) can never
    clobber a key. ``_google_*`` entries are google_service's own
    keychain-failure fallback and pass through untouched.
    """
    out: dict[str, str] = {}
    for provider, value in incoming.items():
        if value in (KEY_SENTINEL, ""):
            out[provider] = existing.get(provider, value)
        elif provider.startswith("_google_"):
            out[provider] = value
        else:
            stored = keychain.set_secret(LLM_KEYCHAIN_SERVICE, provider, value)
            out[provider] = KEY_SENTINEL if stored else value
    return out


def _migrate_plaintext_keys(s: Settings, path: Path) -> Settings:
    """Move raw LLM keys out of settings.json into the Keychain (first load)."""
    keys = dict(s.api_keys)
    moved = 0
    for provider, value in keys.items():
        if provider.startswith("_google_") or not value or value == KEY_SENTINEL:
            continue
        if keychain.set_secret(LLM_KEYCHAIN_SERVICE, provider, value):
            keys[provider] = KEY_SENTINEL
            moved += 1
    if not moved:
        return s
    s = s.model_copy(update={"api_keys": keys})
    path.write_text(s.model_dump_json(indent=2))
    path.chmod(0o600)
    logger.info("Moved %d API key(s) from settings.json into the Keychain.", moved)
    return s


def resolve_api_key(settings: Settings, provider: str) -> str:
    """The real API key for a provider.

    Sentinel → read the Keychain. Anything else is used as-is: a raw
    legacy/fallback value from settings.json, or a just-typed key passing
    through ``/llm/test`` before it's ever saved.
    """
    value = settings.api_keys.get(provider, "")
    if value == KEY_SENTINEL:
        return keychain.get_secret(LLM_KEYCHAIN_SERVICE, provider) or ""
    return value


def reset_cache() -> None:
    """Forget the cached settings (after a data reset)."""
    global _cached
    with _lock:
        _cached = None
