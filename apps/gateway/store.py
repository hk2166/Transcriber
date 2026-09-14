"""User + metering operations. The free tier lives here: a per-user monthly
token cap that rolls over on the first request of a new calendar month."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime

import config

__all__ = [
    "account",
    "block",
    "create_user",
    "current_period",
    "list_users",
    "record_usage",
    "reset_usage",
    "set_limit",
    "unblock",
    "user_by_token",
    "user_public",
]


def current_period() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_user(conn: sqlite3.Connection, email: str, *, token_limit: int | None = None) -> dict:
    """Create (or return) the user for ``email`` and mint a fresh API token.

    Returns the public user dict plus a one-time ``token`` — the only time the
    raw token is ever available; we store only its hash.
    """
    email = email.strip().lower()
    existing = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    raw = "cfb_" + secrets.token_urlsafe(24)
    if existing is not None:
        conn.execute(
            "UPDATE users SET token_hash = ? WHERE id = ?", (_hash(raw), existing["id"])
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (existing["id"],)).fetchone()
    else:
        cursor = conn.execute(
            "INSERT INTO users (email, token_hash, token_limit, period) VALUES (?, ?, ?, ?)",
            (email, _hash(raw), token_limit or config.DEFAULT_TOKEN_LIMIT, current_period()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return {**user_public(row), "token": raw}


def user_by_token(conn: sqlite3.Connection, raw_token: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM users WHERE token_hash = ?", (_hash(raw_token),)
    ).fetchone()


def _roll_period(conn: sqlite3.Connection, row: sqlite3.Row) -> sqlite3.Row:
    """Reset the used-count on the first request of a new month."""
    period = current_period()
    if row["period"] != period:
        conn.execute(
            "UPDATE users SET tokens_used = 0, period = ? WHERE id = ?", (period, row["id"])
        )
        conn.commit()
        return conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
    return row


def remaining(conn: sqlite3.Connection, row: sqlite3.Row) -> int:
    row = _roll_period(conn, row)
    return max(0, row["token_limit"] - row["tokens_used"])


def account(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """Public user dict with this month's remaining tokens, after a period roll."""
    row = _roll_period(conn, row)
    pub = user_public(row)
    pub["remaining"] = max(0, row["token_limit"] - row["tokens_used"])
    return pub


def record_usage(
    conn: sqlite3.Connection, user_id: int, *, model: str, prompt: int, completion: int
) -> None:
    total = int(prompt) + int(completion)
    conn.execute(
        "INSERT INTO usage_events (user_id, model, prompt_tokens, completion_tokens, total_tokens) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, model, prompt, completion, total),
    )
    conn.execute(
        "UPDATE users SET tokens_used = tokens_used + ? WHERE id = ?", (total, user_id)
    )
    conn.commit()


def list_users(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return [user_public(_roll_period(conn, r)) for r in rows]


def set_limit(conn: sqlite3.Connection, user_id: int, token_limit: int) -> bool:
    cur = conn.execute(
        "UPDATE users SET token_limit = ? WHERE id = ?", (max(0, int(token_limit)), user_id)
    )
    conn.commit()
    return cur.rowcount > 0


def reset_usage(conn: sqlite3.Connection, user_id: int) -> bool:
    cur = conn.execute(
        "UPDATE users SET tokens_used = 0, period = ? WHERE id = ?",
        (current_period(), user_id),
    )
    conn.commit()
    return cur.rowcount > 0


def block(conn: sqlite3.Connection, user_id: int) -> bool:
    return _set_status(conn, user_id, "blocked")


def unblock(conn: sqlite3.Connection, user_id: int) -> bool:
    return _set_status(conn, user_id, "active")


def _set_status(conn: sqlite3.Connection, user_id: int, status: str) -> bool:
    cur = conn.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
    conn.commit()
    return cur.rowcount > 0


def user_public(row: sqlite3.Row) -> dict:
    """A user without the token hash — safe for the admin API and /auth/me."""
    return {
        "id": row["id"],
        "email": row["email"],
        "status": row["status"],
        "token_limit": row["token_limit"],
        "tokens_used": row["tokens_used"],
        "period": row["period"],
        "created_at": row["created_at"],
    }
