"""SQLite connection + a tiny forward-only migration runner (no ORM).

Migrations are numbered ``NNNN_name.sql`` files in ``migrations/``, applied in
filename order and recorded in ``schema_migrations`` so each runs exactly once.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["connect"]

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(path: str | Path) -> sqlite3.Connection:
    """Open ``path`` (or ``":memory:"``), enable FKs, and apply migrations.

    Returns a connection with ``row_factory = sqlite3.Row`` so repository
    functions can read columns by name. ``check_same_thread=False`` because
    the app uses one connection from both the event loop and worker threads;
    all writes go through the repository, which the app serialises.
    """
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version TEXT PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}

    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = sql_file.name
        if version in applied:
            continue
        logger.info("Applying migration %s", version)
        conn.executescript(sql_file.read_text())
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        conn.commit()
