"""One backend per data directory.

Two backends on the same ``meetings.db`` would both run startup
reconciliation and post-process the same interrupted meeting at once — and if
anything ever re-spawns the backend in a loop (the 2026-10-15 resource-tracker
crash), each copy would start more work. An exclusive ``flock`` on a file next
to the DB makes the second one refuse to start. The OS drops the lock the
moment its holder dies, so a crash never leaves a stale lock behind.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import signal
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class AnotherInstanceRunning(RuntimeError):
    """Another live backend already holds the lock."""


def acquire(path: Path, timeout_s: float = 10.0) -> int:
    """Take the lock at ``path`` and return its fd; hold it for the process life.

    Waits up to ``timeout_s`` so a relaunched app's backend can outlast its
    predecessor's shutdown (orphan detection + graceful stop, see
    :func:`exit_when_orphaned`), then raises :class:`AnotherInstanceRunning`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise AnotherInstanceRunning(f"another backend holds {path}") from None
            time.sleep(0.1)
            continue
        # Holder's pid, for whoever is debugging a refused start.
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        return fd


def release(fd: int) -> None:
    """Drop the lock (app shutdown)."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


async def exit_when_orphaned(poll_s: float = 1.0) -> None:
    """Stop this backend once the process that launched it is gone.

    The desktop shell kills its sidecar on a normal quit, but a crash or
    force-quit skips that — the backend lingers (re-parented to launchd),
    keeps the lock, and the relaunched app's backend is refused. SIGTERM
    ourselves so uvicorn runs the normal shutdown: finalize any recording,
    close the DB, release the lock. A parent of launchd (pid 1) counts too:
    the launcher may already have died while this process was still starting.
    """
    parent = os.getppid()
    while True:
        await asyncio.sleep(poll_s)
        ppid = os.getppid()
        if ppid != parent or ppid == 1:
            logger.warning("Launcher (pid %d) exited; shutting down.", parent)
            os.kill(os.getpid(), signal.SIGTERM)
            return
