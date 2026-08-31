"""Detect a live meeting — any platform — and let the UI offer to record.

Two signals, checked by a lifespan-owned poller (only while the
``auto_record`` setting isn't "off"):

1. **Named apps** — helper processes that exist *only during a call*
   (Zoom's CptHost, Webex's CiscoCollabHost). Instant, and lets the UI say
   "Zoom call detected".
2. **Microphone in use** — CoreAudio's is-running-somewhere flag on the
   default input device. This is the universal catch-all: Google Meet in a
   browser, Teams, Slack huddles, FaceTime, Discord… anything that opens the
   mic. Debounced (two consecutive polls ≈ 10 s) so a quick voice memo or
   dictation burst doesn't nag, and skipped entirely while Confab itself is
   recording (that mic user is us).

The UI polls ``GET /system/meeting-app``; on a new episode it surfaces the
window / notifies and prompts (or auto-starts) per the setting.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import subprocess
import time
from typing import Any

from settings import get_settings

logger = logging.getLogger(__name__)

POLL_SECONDS = 5
#: Consecutive mic-in-use polls before the generic signal counts as a meeting.
MIC_DEBOUNCE_POLLS = 2

#: (display name, exact process name that exists only during a live call)
DETECTORS: list[tuple[str, str]] = [
    ("Zoom", "CptHost"),  # Zoom's meeting window host
    ("Webex", "CiscoCollabHost"),
]

_state: dict[str, Any] = {"app": None, "since": None, "source": None}
_mic_streak = 0


def current() -> dict[str, Any]:
    """The currently detected meeting (or ``{"app": None}``)."""
    return dict(_state)


def _scan_processes() -> str | None:
    for app, process in DETECTORS:
        try:
            probe = subprocess.run(
                ["pgrep", "-x", process], capture_output=True, timeout=3
            )
        except Exception:
            continue
        if probe.returncode == 0:
            return app
    return None


# --- CoreAudio: is any process using the default microphone? -----------------

_FRAMEWORK = "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
_SYSTEM_OBJECT = 1  # kAudioObjectSystemObject


class _PropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


def mic_in_use() -> bool:
    """True if any process has the default input device running.

    Best-effort: any CoreAudio hiccup reads as "not in use" rather than a
    crash — the named-app detectors still work regardless.
    """
    try:
        core_audio = ctypes.CDLL(_FRAMEWORK)
        device = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(device))
        address = _PropertyAddress(
            _fourcc("dIn "),  # kAudioHardwarePropertyDefaultInputDevice
            _fourcc("glob"),  # kAudioObjectPropertyScopeGlobal
            0,
        )
        status = core_audio.AudioObjectGetPropertyData(
            _SYSTEM_OBJECT, ctypes.byref(address), 0, None,
            ctypes.byref(size), ctypes.byref(device),
        )
        if status != 0 or device.value == 0:
            return False

        running = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(running))
        address = _PropertyAddress(
            _fourcc("gone"),  # kAudioDevicePropertyDeviceIsRunningSomewhere
            _fourcc("glob"),
            0,
        )
        status = core_audio.AudioObjectGetPropertyData(
            device.value, ctypes.byref(address), 0, None,
            ctypes.byref(size), ctypes.byref(running),
        )
        return status == 0 and bool(running.value)
    except Exception:
        return False


# --- The poll step (pure-ish for tests) --------------------------------------

def _set(app: str | None, source: str | None) -> None:
    if app != _state["app"] or source != _state["source"]:
        _state.update(
            app=app, source=source, since=time.time() if app else None
        )
        if app:
            logger.info("Meeting detected: %s (%s)", app, source)


def _step(*, recording: bool, named: str | None, mic: bool) -> None:
    """One poll: fold the signals into ``_state`` (testable, no I/O)."""
    global _mic_streak
    if recording:
        # The mic user is (or includes) us — stand down for the session.
        _mic_streak = 0
        _set(None, None)
        return
    if named:
        _mic_streak = 0
        _set(named, "app")
        return
    if mic:
        _mic_streak += 1
        if _mic_streak >= MIC_DEBOUNCE_POLLS:
            _set("Meeting", "microphone")
        return
    _mic_streak = 0
    _set(None, None)


async def poller() -> None:
    """Background task: keep ``_state`` current. Cancelled at shutdown."""
    while True:
        try:
            if get_settings().auto_record != "off":
                from sessions import manager  # late: avoids import-order knots

                recording = manager.active is not None
                named = None if recording else await asyncio.to_thread(_scan_processes)
                mic = (
                    False
                    if recording or named
                    else await asyncio.to_thread(mic_in_use)
                )
                _step(recording=recording, named=named, mic=mic)
            elif _state["app"] is not None:
                _step(recording=False, named=None, mic=False)
        except Exception:
            logger.exception("Meeting scan failed.")
        await asyncio.sleep(POLL_SECONDS)
