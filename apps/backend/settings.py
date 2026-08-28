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
    whisper_model: str = "small"
    ollama_model: str = "llama3.2"
    vad_threshold: float = 0.5
    default_source: str = "both"
    auto_summarize: bool = True
    #: What to do when a meeting app (Zoom/Webex) starts a call:
    #: "off" = ignore, "prompt" = offer to record, "auto" = start recording.
    auto_record: Literal["off", "prompt", "auto"] = "prompt"


def _path() -> Path:
    return default_recordings_dir().parent / "settings.json"


def get_settings() -> Settings:
    global _cached
    with _lock:
        if _cached is None:
            path = _path()
            if path.exists():
                try:
                    _cached = Settings.model_validate_json(path.read_text())
                except Exception:
                    logger.exception("Bad settings.json — using defaults.")
                    _cached = Settings()
            else:
                _cached = Settings()
    return _cached


def save_settings(new: Settings) -> Settings:
    global _cached
    with _lock:
        _path().write_text(new.model_dump_json(indent=2))
        _cached = new
    logger.info("Settings saved: %s", new.model_dump())
    return _cached


def reset_cache() -> None:
    """Forget the cached settings (after a data reset)."""
    global _cached
    with _lock:
        _cached = None
