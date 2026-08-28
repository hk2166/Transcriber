"""Whisper model pre-download with visible progress.

``WhisperTranscriber`` downloads its model into the HF cache on first
construction — mid-first-recording, invisibly. This module lets the UI
pre-fetch the same files with a progress bar: the download runs in a worker
thread while a monitor thread sizes the cache directory, and the UI polls
``status()``.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: dict[str, Any] = {
    "state": "unknown",  # unknown | absent | downloading | ready | error
    "model": None,
    "progress": 0.0,
    "done_bytes": 0,
    "total_bytes": 0,
    "error": None,
}


def _repo_for(model_size: str) -> str:
    """Same resolution faster-whisper uses for bare size names."""
    return f"Systran/faster-whisper-{model_size}"


def _repo_cache_dir(repo: str) -> Path:
    from huggingface_hub.constants import HF_HUB_CACHE

    return Path(HF_HUB_CACHE) / f"models--{repo.replace('/', '--')}"


def _cache_bytes(repo: str) -> int:
    root = _repo_cache_dir(repo)
    if not root.is_dir():
        return 0
    total = 0
    # huggingface_hub streams to "<hash>.incomplete" then renames, so a path
    # yielded by rglob can vanish before we stat it — tolerate that.
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _is_cached(repo: str) -> bool:
    from huggingface_hub import snapshot_download

    try:
        snapshot_download(repo, local_files_only=True)
        return True
    except Exception:
        return False


def status(model_size: str) -> dict[str, Any]:
    """Current download state for the configured model (UI polls this)."""
    repo = _repo_for(model_size)
    with _lock:
        if _state["state"] == "downloading" and _state["model"] == model_size:
            return dict(_state)
    # A finished cache wins over a stale error: a transient hiccup may have
    # flipped state to "error" while the fetch actually completed.
    if _is_cached(repo):
        return {
            "state": "ready",
            "model": model_size,
            "progress": 1.0,
            "done_bytes": 0,
            "total_bytes": 0,
            "error": None,
        }
    with _lock:
        if _state["state"] == "error" and _state["model"] == model_size:
            return dict(_state)
    return {
        "state": "absent",
        "model": model_size,
        "progress": 0.0,
        "done_bytes": 0,
        "total_bytes": 0,
        "error": None,
    }


def start(model_size: str) -> dict[str, Any]:
    """Begin downloading in the background (no-op if running or cached)."""
    with _lock:
        if _state["state"] == "downloading":
            return dict(_state)
    current = status(model_size)
    if current["state"] == "ready":
        return current
    with _lock:
        _state.update(
            state="downloading",
            model=model_size,
            progress=0.0,
            done_bytes=0,
            total_bytes=0,
            error=None,
        )
    threading.Thread(
        target=_download, args=(model_size,), name="model-download", daemon=True
    ).start()
    with _lock:
        return dict(_state)


def _download(model_size: str) -> None:
    repo = _repo_for(model_size)
    try:
        from huggingface_hub import HfApi, snapshot_download

        info = HfApi().model_info(repo, files_metadata=True)
        total = sum(s.size or 0 for s in info.siblings)
        already = _cache_bytes(repo)
        with _lock:
            _state.update(total_bytes=total, done_bytes=already)

        error: list[BaseException] = []

        def _fetch() -> None:
            try:
                snapshot_download(repo)
            except BaseException as exc:  # noqa: BLE001 - reported via state
                error.append(exc)

        fetcher = threading.Thread(target=_fetch, name="model-fetch", daemon=True)
        fetcher.start()
        while fetcher.is_alive():
            done = _cache_bytes(repo)
            with _lock:
                _state.update(
                    done_bytes=done,
                    progress=min(done / total, 0.99) if total else 0.0,
                )
            time.sleep(0.4)
        fetcher.join()
        if error:
            raise error[0]

        with _lock:
            _state.update(state="ready", progress=1.0, done_bytes=total)
        logger.info("Whisper model %s downloaded (%d bytes).", model_size, total)
    except BaseException as exc:  # noqa: BLE001 - surfaced to the UI
        logger.exception("Model download failed for %s.", model_size)
        with _lock:
            _state.update(state="error", error=str(exc))
