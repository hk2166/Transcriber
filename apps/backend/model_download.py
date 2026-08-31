"""Speech-model pre-download with visible progress (Whisper or Parakeet).

The active engine's model otherwise downloads into the HF cache on the first
recording, invisibly. This lets the UI pre-fetch it with a progress bar: the
download runs in a worker thread while a monitor thread sizes the cache
directory, and the UI polls ``status()``.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from settings import get_settings

logger = logging.getLogger(__name__)

#: engine id → (HF repo, rough int8 download size for the progress bar)
_PARAKEET = {
    "parakeet-v2": ("istupakov/parakeet-tdt-0.6b-v2-onnx", 650_000_000),
    "parakeet-v3": ("istupakov/parakeet-tdt-0.6b-v3-onnx", 680_000_000),
}
#: A populated cache dir above this size counts as "downloaded" for engines
#: whose exact file set we don't enumerate (Parakeet: onnx-asr fetches a subset).
_READY_MIN_BYTES = 40_000_000

_lock = threading.Lock()
_state: dict[str, Any] = {
    "state": "unknown",  # unknown | absent | downloading | ready | error
    "model": None,
    "progress": 0.0,
    "done_bytes": 0,
    "total_bytes": 0,
    "error": None,
}


def _active() -> tuple[str, str, str, int]:
    """(engine, repo, family, expected_bytes) for the configured engine."""
    engine = get_settings().transcription_engine
    if engine in _PARAKEET:
        repo, expected = _PARAKEET[engine]
        return engine, repo, "parakeet", expected
    size = engine.split("-", 1)[1] if engine.startswith("whisper-") else "small"
    return engine, f"Systran/faster-whisper-{size}", "whisper", 0


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


def _is_cached(repo: str, family: str) -> bool:
    if family == "whisper":
        from huggingface_hub import snapshot_download

        try:
            snapshot_download(repo, local_files_only=True)
            return True
        except Exception:
            return False
    # Parakeet: onnx-asr downloads a subset (int8 + configs), so a full
    # snapshot check would wrongly report "absent" — use a size heuristic.
    return _cache_bytes(repo) > _READY_MIN_BYTES


def _blank(engine: str, state: str, progress: float = 0.0) -> dict[str, Any]:
    return {
        "state": state,
        "model": engine,
        "progress": progress,
        "done_bytes": 0,
        "total_bytes": 0,
        "error": None,
    }


def status() -> dict[str, Any]:
    """Download state of the active engine's model (UI polls this)."""
    engine, repo, family, _ = _active()
    with _lock:
        if _state["state"] == "downloading" and _state["model"] == engine:
            return dict(_state)
    if _is_cached(repo, family):
        return _blank(engine, "ready", 1.0)
    with _lock:
        if _state["state"] == "error" and _state["model"] == engine:
            return dict(_state)
    return _blank(engine, "absent")


def start() -> dict[str, Any]:
    """Begin downloading the active engine's model (no-op if running/cached)."""
    with _lock:
        if _state["state"] == "downloading":
            return dict(_state)
    if status()["state"] == "ready":
        return status()
    engine, repo, family, expected = _active()
    with _lock:
        _state.update(
            state="downloading",
            model=engine,
            progress=0.0,
            done_bytes=0,
            total_bytes=expected,
            error=None,
        )
    threading.Thread(
        target=_download,
        args=(engine, repo, family, expected),
        name="model-download",
        daemon=True,
    ).start()
    with _lock:
        return dict(_state)


def _fetch_model(engine: str, repo: str, family: str) -> None:
    if family == "whisper":
        from huggingface_hub import snapshot_download

        snapshot_download(repo)
    else:
        import onnx_asr

        from packages.transcription import PARAKEET_MODELS

        # Downloads the int8 weights + configs, then discards the loaded model.
        onnx_asr.load_model(PARAKEET_MODELS[engine], quantization="int8")


def _download(engine: str, repo: str, family: str, expected: int) -> None:
    try:
        total = expected
        if family == "whisper":
            from huggingface_hub import HfApi

            try:
                info = HfApi().model_info(repo, files_metadata=True)
                total = sum(s.size or 0 for s in info.siblings)
            except Exception:
                total = expected
        with _lock:
            _state.update(total_bytes=total, done_bytes=_cache_bytes(repo))

        error: list[BaseException] = []

        def _fetch() -> None:
            try:
                _fetch_model(engine, repo, family)
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
            _state.update(state="ready", progress=1.0, done_bytes=_cache_bytes(repo))
        logger.info("Model %s ready.", engine)
    except BaseException as exc:  # noqa: BLE001 - surfaced to the UI
        logger.exception("Model download failed for %s.", engine)
        with _lock:
            _state.update(state="error", error=str(exc))
