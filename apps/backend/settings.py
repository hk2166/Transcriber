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

from packages.audio import default_recordings_dir

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cached: Settings | None = None


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
    #: Per-provider API keys, e.g. {"openai": "sk-…"}. Stored in settings.json
    #: (chmod 600) — local single-user app.
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
                except Exception:
                    logger.exception("Bad settings.json — using defaults.")
                    _cached = Settings()
            else:
                _cached = Settings()
    return _cached


def save_settings(new: Settings) -> Settings:
    global _cached
    with _lock:
        path = _path()
        path.write_text(new.model_dump_json(indent=2))
        path.chmod(0o600)  # may hold API keys — owner-only
        _cached = new
    redacted = new.model_dump()
    redacted["api_keys"] = {k: "•••" for k in redacted.get("api_keys", {})}
    logger.info("Settings saved: %s", redacted)
    return _cached


def reset_cache() -> None:
    """Forget the cached settings (after a data reset)."""
    global _cached
    with _lock:
        _cached = None
