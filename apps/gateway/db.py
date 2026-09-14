"""SQLite store for the gateway — users + usage events. One file, no ORM.

A skeleton store: fine for a single instance. A real deployment swaps this for
Postgres and puts the token *hash* behind a proper secrets story (already hashed
here) plus row-level rate limits.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    token_hash    TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'active',   -- active | blocked
    token_limit   INTEGER NOT NULL,                 -- monthly cap
    tokens_used   INTEGER NOT NULL DEFAULT 0,
    period        TEXT NOT NULL DEFAULT '',          -- 'YYYY-MM' the used-count is for
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS usage_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ts                TEXT NOT NULL DEFAULT (datetime('now')),
    model             TEXT NOT NULL DEFAULT '',
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_events(user_id, ts);
"""

_conn: sqlite3.Connection | None = None


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = connect(config.DB_PATH)
    return _conn


def close_db() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
