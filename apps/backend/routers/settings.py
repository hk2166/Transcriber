"""Settings, system-readiness (for onboarding), and full data reset."""

from __future__ import annotations

import logging
from typing import Any

import ollama
from fastapi import APIRouter
from pydantic import BaseModel

import llm
import meeting_detect
import model_download
import search_index
import settings as settings_module
import speaker_pack
from database import close_db, db_path, get_db
from packages.audio import SystemAudioCapture, default_recordings_dir
from packages.intelligence import PROVIDERS, LLMUnavailable
from packages.transcription import ASR_ENGINES
from sessions import manager
from settings import Settings, get_settings, save_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


def _redacted(s: Settings) -> Settings:
    """Never hand raw API keys to the client — only presence.

    Every non-empty entry (Keychain sentinel, legacy plaintext, or a
    ``_google_*`` fallback) comes back as the sentinel; the UI's password
    fields show a masked placeholder, and PUTting the sentinel back means
    "unchanged" (save_settings preserves the stored value)."""
    return s.model_copy(
        update={
            "api_keys": {
                k: (settings_module.KEY_SENTINEL if v else "")
                for k, v in s.api_keys.items()
            }
        }
    )


@router.get("/settings")
def read_settings() -> Settings:
    return _redacted(get_settings())


@router.put("/settings")
def update_settings(new: Settings) -> Settings:
    engine_changed = new.transcription_engine != get_settings().transcription_engine
    saved = save_settings(new)
    if engine_changed:
        # Drop the cached transcriber so the new engine loads next recording
        # (the packaged app also hard-restarts; this covers dev + correctness).
        import sessions

        sessions.reset_transcriber()
        logger.info("Transcription engine → %s (transcriber reset).", new.transcription_engine)
    return _redacted(saved)


class SystemStatus(BaseModel):
    ollama_available: bool
    ollama_models: list[str]
    blackhole_available: bool
    whisper_model: str


@router.get("/system/status")
def system_status() -> SystemStatus:
    """Readiness probe the first-run wizard polls."""
    try:
        ollama_models = [m.model for m in ollama.list().models]
        ollama_available = True
    except Exception:
        ollama_models = []
        ollama_available = False

    try:
        SystemAudioCapture.find_device()
        blackhole_available = True
    except Exception:
        blackhole_available = False

    return SystemStatus(
        ollama_available=ollama_available,
        ollama_models=ollama_models,
        blackhole_available=blackhole_available,
        whisper_model=get_settings().whisper_model,
    )


@router.get("/llm/providers")
def llm_providers() -> list[dict[str, Any]]:
    """The provider registry the Settings UI renders."""
    return [
        {
            "id": spec.id,
            "label": spec.label,
            "default_model": spec.default_model,
            "needs_key": spec.needs_key,
            "needs_base_url": spec.id == "custom",
            "key_url": spec.key_url,
            "local": spec.protocol == "ollama" or spec.id == "custom",
        }
        for spec in PROVIDERS
    ]


@router.post("/llm/test")
def llm_test(candidate: Settings) -> dict[str, Any]:
    """Try one tiny completion with the GIVEN (unsaved) settings.

    Lets the UI validate a key before the user hits Save.
    """
    try:
        client = llm.client_for(candidate)
        reply = client.complete("Reply with only the word OK.")
        ok = bool(reply and reply.strip())
        return {"ok": ok, "reply": (reply or "").strip()[:40]}
    except LLMUnavailable as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("LLM test failed unexpectedly.")
        return {"ok": False, "error": str(exc)}


@router.get("/asr/engines")
def asr_engines() -> list[dict[str, Any]]:
    """Transcription-engine registry the Settings UI renders — with per-engine
    download state and which one is active."""
    active = get_settings().transcription_engine
    return [
        {
            "id": spec.id,
            "label": spec.label,
            "note": spec.note,
            "languages": spec.languages,
            "size_mb": spec.size_mb,
            "family": spec.family,
            "downloaded": model_download.is_downloaded(spec.id),
            "active": spec.id == active,
        }
        for spec in ASR_ENGINES
    ]


@router.get("/system/model-status")
def model_status(engine: str | None = None) -> dict[str, Any]:
    """Download state of an engine's model (active if unspecified)."""
    return model_download.status(engine)


@router.post("/system/model-download")
def model_download_start(engine: str | None = None) -> dict[str, Any]:
    """Pre-fetch an engine's model with visible progress (active if unspecified)."""
    return model_download.start(engine)


@router.get("/system/meeting-app")
def meeting_app() -> dict[str, Any]:
    """Currently detected meeting app (Zoom/Webex), if any."""
    detected = meeting_detect.current()
    detected["recording"] = manager.active is not None
    detected["mode"] = get_settings().auto_record
    return detected


@router.get("/system/speaker-pack")
def speaker_pack_status() -> dict[str, Any]:
    """Install state of the optional diarization pack."""
    return speaker_pack.status()


@router.post("/system/speaker-pack-install")
def speaker_pack_install() -> dict[str, Any]:
    """Download + install the speaker pack in the background."""
    return speaker_pack.start_install()


@router.post("/system/reset")
def reset_all_data() -> dict[str, bool]:
    """Delete every meeting, recording, the index, and settings ('delete all data')."""
    close_db()
    app_dir = default_recordings_dir().parent
    db_path().unlink(missing_ok=True)
    (app_dir / "search_index.npz").unlink(missing_ok=True)
    (app_dir / "settings.json").unlink(missing_ok=True)
    for wav in default_recordings_dir().glob("*.wav"):
        wav.unlink(missing_ok=True)

    search_index.reset()
    settings_module.reset_cache()
    get_db()  # reopen a fresh, migrated database
    logger.info("All data reset.")
    return {"reset": True}
