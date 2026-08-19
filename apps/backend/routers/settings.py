"""Settings, system-readiness (for onboarding), and full data reset."""

from __future__ import annotations

import logging

import ollama
from fastapi import APIRouter
from pydantic import BaseModel

import search_index
import settings as settings_module
from database import close_db, db_path, get_db
from packages.audio import SystemAudioCapture, default_recordings_dir
from settings import Settings, get_settings, save_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


@router.get("/settings")
def read_settings() -> Settings:
    return get_settings()


@router.put("/settings")
def update_settings(new: Settings) -> Settings:
    return save_settings(new)


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
