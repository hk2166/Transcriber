"""The live speech-segment queue is bounded: a lagging transcriber drops
speech (warning once) instead of growing memory without bound."""

import asyncio
import logging

import sessions


def _session(maxsize: int) -> sessions.AudioSession:
    s = object.__new__(sessions.AudioSession)  # no audio devices needed
    s._seg_queue = asyncio.Queue(maxsize=maxsize)
    s._seg_drops = 0
    return s


def test_overflow_drops_and_warns_once(caplog):
    s = _session(maxsize=2)
    with caplog.at_level(logging.WARNING, logger="sessions"):
        for i in range(5):
            s._enqueue_segment((f"seg{i}", 0.0))

    assert s._seg_queue.qsize() == 2       # bounded — never grew past maxsize
    assert s._seg_drops == 3               # the overflow was counted…
    assert sum("dropping live speech" in r.message for r in caplog.records) == 1  # …and reported once


def test_end_sentinel_is_never_dropped():
    s = _session(maxsize=1)
    s._enqueue_segment(("seg0", 0.0))      # queue is now full
    s._end_segments()                      # must still deliver None
    assert s._seg_queue.get_nowait() is None
