"""Application database — one shared SQLite connection for the process.

All access happens on the event loop (session lifecycle + REST reads), so a
single connection is enough. Opened at startup so migrations run — and any
error surfaces — before the first recording.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from packages.audio import default_recordings_dir
from packages.storage import connect

logger = logging.getLogger(__name__)

_conn: sqlite3.Connection | None = None


def db_path() -> Path:
    """``~/Library/Application Support/MeetingMind/meetings.db`` (dir ensured)."""
    return default_recordings_dir().parent / "meetings.db"


def get_db() -> sqlite3.Connection:
    """Return the shared connection, opening + migrating it on first use."""
    global _conn
    if _conn is None:
        path = db_path()
        _conn = connect(path)
        logger.info("Database ready at %s", path)
    return _conn


def close_db() -> None:
    """Close the shared connection (app shutdown)."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
