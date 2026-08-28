"""Detect running meeting apps via their in-call helper processes.

A lifespan-owned asyncio task polls every few seconds (only while the
``auto_record`` setting is not "off"); the UI polls ``GET
/system/meeting-app`` and prompts or auto-starts a recording.

Detection is deliberately process-based and conservative: each entry names a
helper process that exists *only while a call is live*, so a merely-open app
never triggers a prompt.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from typing import Any

from settings import get_settings

logger = logging.getLogger(__name__)

POLL_SECONDS = 5

#: (display name, exact process name that exists only during a live call)
DETECTORS: list[tuple[str, str]] = [
    ("Zoom", "CptHost"),  # Zoom's meeting window host
    ("Webex", "CiscoCollabHost"),
]

_state: dict[str, Any] = {"app": None, "since": None}


def current() -> dict[str, Any]:
    """The currently detected meeting app (or ``{"app": None}``)."""
    return dict(_state)


def _scan() -> str | None:
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


async def poller() -> None:
    """Background task: keep ``_state`` current. Cancelled at shutdown."""
    while True:
        try:
            if get_settings().auto_record != "off":
                app = await asyncio.to_thread(_scan)
                if app != _state["app"]:
                    _state.update(app=app, since=time.time() if app else None)
                    if app:
                        logger.info("Meeting app detected: %s", app)
            elif _state["app"] is not None:
                _state.update(app=None, since=None)
        except Exception:
            logger.exception("Meeting-app scan failed.")
        await asyncio.sleep(POLL_SECONDS)
