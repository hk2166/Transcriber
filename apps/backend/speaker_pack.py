"""The optional speaker pack: diarization for the packaged (torch-free) app.

The main app ships without torch (see PACKAGING.md). Speaker labels come from
a separately-downloaded pack: a self-contained PyInstaller binary
(``confab-speakers``, built by scripts/build-speaker-pack.sh) plus a bundled
HF model cache, installed under the app-data dir. The backend shells out to
it and reads JSON speaker turns — the ``list[SpeakerTurn]`` contract is
identical to in-process pyannote, so everything downstream is unchanged.

In dev (torch importable) the pack is never needed; postprocess_job tries
in-process first and falls back here.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from packages.audio import default_recordings_dir
from packages.diarization import SpeakerTurn

logger = logging.getLogger(__name__)

#: Release asset produced by scripts/build-speaker-pack.sh and uploaded to the
#: GitHub release. 404 until published — the UI shows "not yet available".
PACK_URL = (
    "https://github.com/hk2166/Transcriber/releases/download/"
    "v0.1.0/confab-speakers-macos-arm64.zip"
)

DIARIZE_TIMEOUT_SECONDS = 30 * 60

_lock = threading.Lock()
_state: dict[str, Any] = {
    "state": "idle",  # idle | downloading | error
    "progress": 0.0,
    "error": None,
}


def _extract_preserving_symlinks(zip_path: Path, dest: Path) -> None:
    """Unzip while recreating symlinks and executable bits.

    ``ZipFile.extractall`` writes a symlink entry as a regular file whose
    *contents* are the link target — which silently corrupts the bundled HF
    model cache (its blobs are symlinked) and the PyInstaller dist's dylib
    aliases. We reproduce symlinks with ``os.symlink`` and restore the exec
    bit from each entry's stored Unix mode.
    """
    import stat as stat_mod

    with zipfile.ZipFile(zip_path) as bundle:
        for info in bundle.infolist():
            target = dest / info.filename
            mode = info.external_attr >> 16
            if stat_mod.S_ISLNK(mode):
                target.parent.mkdir(parents=True, exist_ok=True)
                link_target = bundle.read(info).decode()
                if target.is_symlink() or target.exists():
                    target.unlink()
                os.symlink(link_target, target)
            else:
                bundle.extract(info, dest)
                if mode & 0o111:
                    target.chmod(target.stat().st_mode | 0o755)


def _pack_dir() -> Path:
    return default_recordings_dir().parent / "speaker-pack"


def _binary() -> Path:
    return _pack_dir() / "confab-speakers" / "confab-speakers"


def installed() -> bool:
    binary = _binary()
    return binary.is_file() and os.access(binary, os.X_OK)


def diarize_file(wav_path: str) -> list[SpeakerTurn]:
    """Run the pack binary on a WAV; returns the same turns as pyannote."""
    binary = _binary()
    env = os.environ.copy()
    # The pack carries its own HF cache — fully offline.
    env["HF_HOME"] = str(_pack_dir() / "hf")
    env["HF_HUB_OFFLINE"] = "1"
    result = subprocess.run(
        [str(binary), wav_path],
        capture_output=True,
        text=True,
        env=env,
        timeout=DIARIZE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"speaker pack exited {result.returncode}: {result.stderr[-500:]}"
        )
    return [SpeakerTurn(**turn) for turn in json.loads(result.stdout)]


def status() -> dict[str, Any]:
    with _lock:
        return {**_state, "installed": installed()}


def start_install() -> dict[str, Any]:
    """Download + unpack the pack in the background (no-op if running)."""
    with _lock:
        if _state["state"] == "downloading":
            return {**_state, "installed": installed()}
        _state.update(state="downloading", progress=0.0, error=None)
    threading.Thread(target=_install, name="speaker-pack-install", daemon=True).start()
    return status()


def _install() -> None:
    archive = _pack_dir().parent / "speaker-pack.zip.partial"
    try:
        _pack_dir().mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(PACK_URL, headers={"User-Agent": "Confab"})
        with urllib.request.urlopen(request, timeout=30) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            last_update = 0.0
            with open(archive, "wb") as out:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if total and now - last_update > 0.3:
                        last_update = now
                        with _lock:
                            _state["progress"] = min(done / total, 0.95)
        _extract_preserving_symlinks(archive, _pack_dir())
        _binary().chmod(0o755)
        if not installed():
            raise RuntimeError("Archive did not contain the confab-speakers binary.")
        with _lock:
            _state.update(state="idle", progress=1.0)
        logger.info("Speaker pack installed at %s", _pack_dir())
    except urllib.error.HTTPError as exc:
        message = (
            "The speaker pack isn't published yet — coming in v1.1."
            if exc.code == 404
            else f"Download failed: HTTP {exc.code}"
        )
        logger.warning("Speaker pack install failed: %s", exc)
        with _lock:
            _state.update(state="error", error=message)
    except Exception as exc:
        logger.exception("Speaker pack install failed.")
        with _lock:
            _state.update(state="error", error=str(exc))
    finally:
        archive.unlink(missing_ok=True)
