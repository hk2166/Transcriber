"""A global gate that serializes heavy in-process model work — one job at a time.

Confab loads several large models on demand: the live transcriber (Whisper /
Parakeet), a second Whisper for the post-meeting refine pass, the pyannote
diarizer, and the ONNX embedder. Loading more than one at once spikes memory —
and post-processing is fire-and-forget, so ending several meetings, or the
startup reconciliation resuming a backlog of stranded ones, could fire many
jobs together and exhaust RAM on a modest laptop.

This gate lets exactly one gated job run at a time (``MAX_CONCURRENT`` slots,
default 1); the rest queue and run as slots free. It intentionally does NOT
gate the live recording path, so pressing Record never waits on background
post-processing.

Usage (on the event loop)::

    async with model_gate.slot(f"postprocess:{meeting_id}"):
        ...  # refine / diarize / index — heavy model work
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

logger = logging.getLogger(__name__)

__all__ = ["MAX_CONCURRENT", "slot", "active", "waiting"]

#: How many gated jobs may run at once. 1 = strictly one model job at a time.
MAX_CONCURRENT = 1

_sema: asyncio.Semaphore | None = None
_sema_loop: asyncio.AbstractEventLoop | None = None
_active = 0   # slots currently held
_waiting = 0  # jobs currently blocked waiting for a slot


def _get_sema() -> asyncio.Semaphore:
    """The semaphore bound to the running loop.

    The backend lives on one long-lived event loop, so this creates the
    semaphore exactly once. Rebinding on a loop change keeps it correct if the
    loop is ever replaced (e.g. across tests), instead of raising the
    cross-loop RuntimeError an import-time semaphore would.
    """
    global _sema, _sema_loop, _active, _waiting
    loop = asyncio.get_running_loop()
    if _sema is None or _sema_loop is not loop:
        _sema = asyncio.Semaphore(MAX_CONCURRENT)
        _sema_loop = loop
        _active = 0
        _waiting = 0
    return _sema


@contextlib.asynccontextmanager
async def slot(name: str):
    """Hold one model slot for the duration of the block.

    Blocks until a slot is free, so callers queue instead of loading models
    concurrently. Best-effort logging notes when a job has to wait.
    """
    global _active, _waiting
    sema = _get_sema()
    if sema.locked():
        _waiting += 1
        logger.info("Model gate busy — %s queued (%d waiting).", name, _waiting)
        try:
            await sema.acquire()
        finally:
            _waiting -= 1
    else:
        await sema.acquire()
    _active += 1
    logger.info("Model gate acquired — %s.", name)
    try:
        yield
    finally:
        _active -= 1
        sema.release()
        logger.info("Model gate released — %s.", name)


def active() -> int:
    """How many slots are currently held (0..MAX_CONCURRENT)."""
    return _active


def waiting() -> int:
    """How many jobs are blocked waiting for a slot."""
    return _waiting
