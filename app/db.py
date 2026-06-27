"""SQLite persistence for QR Forge.

Two tables:

* ``codes`` — one row per QR code that was created, holding the payload, the
  styling options it was rendered with, and bookkeeping timestamps.
* ``scans`` — one row per scan of a *tracked* code, recording when it happened
  and the requesting user-agent / referrer.

The database path is taken from the ``QRFORGE_DB`` environment variable so that
tests can point it at a throwaway file. Connections are opened per-call (SQLite
is happy with that) with ``check_same_thread=False`` so FastAPI's threadpool can
use them.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

DEFAULT_DB_PATH = "qrforge.db"


def db_path() -> str:
    """Return the active database path (env-overridable)."""
    return os.environ.get("QRFORGE_DB", DEFAULT_DB_PATH)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Yield a connection with row access by name, committing on success."""
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they do not already exist."""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS codes (
                id          TEXT PRIMARY KEY,
                payload     TEXT NOT NULL,
                fill_color  TEXT NOT NULL,
                back_color  TEXT NOT NULL,
                box_size    INTEGER NOT NULL,
                border      INTEGER NOT NULL,
                error_correction TEXT NOT NULL,
                tracked     INTEGER NOT NULL DEFAULT 0,
                target_url  TEXT,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scans (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                code_id    TEXT NOT NULL,
                scanned_at TEXT NOT NULL,
                user_agent TEXT,
                referrer   TEXT,
                FOREIGN KEY (code_id) REFERENCES codes(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_scans_code ON scans(code_id);
            """
        )


def insert_code(row: dict[str, Any]) -> None:
    """Persist a newly created QR code."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO codes
                (id, payload, fill_color, back_color, box_size, border,
                 error_correction, tracked, target_url, created_at)
            VALUES
                (:id, :payload, :fill_color, :back_color, :box_size, :border,
                 :error_correction, :tracked, :target_url, :created_at)
            """,
            row,
        )


def get_code(code_id: str) -> dict[str, Any] | None:
    """Return a single code row as a dict, or ``None`` if it does not exist."""
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM codes WHERE id = ?", (code_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_codes() -> list[dict[str, Any]]:
    """Return all codes (newest first) with their scan counts."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT c.*, COUNT(s.id) AS scan_count
            FROM codes c
            LEFT JOIN scans s ON s.code_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC, c.id DESC
            """
        )
        return [dict(r) for r in cur.fetchall()]


def record_scan(code_id: str, when: str, user_agent: str | None, referrer: str | None) -> None:
    """Append a scan event for a tracked code."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO scans (code_id, scanned_at, user_agent, referrer) VALUES (?, ?, ?, ?)",
            (code_id, when, user_agent, referrer),
        )


def scan_stats(code_id: str) -> dict[str, Any]:
    """Return aggregate scan analytics for a code.

    Includes total scans, distinct user-agents, first/last scan timestamps and
    a per-user-agent breakdown.
    """
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n, MIN(scanned_at) AS first, MAX(scanned_at) AS last "
            "FROM scans WHERE code_id = ?",
            (code_id,),
        ).fetchone()

        by_agent = conn.execute(
            """
            SELECT COALESCE(user_agent, '(unknown)') AS user_agent, COUNT(*) AS count
            FROM scans WHERE code_id = ?
            GROUP BY user_agent
            ORDER BY count DESC
            """,
            (code_id,),
        ).fetchall()

        recent = conn.execute(
            "SELECT scanned_at, user_agent, referrer FROM scans "
            "WHERE code_id = ? ORDER BY scanned_at DESC, id DESC LIMIT 10",
            (code_id,),
        ).fetchall()

    return {
        "total_scans": total["n"],
        "first_scan": total["first"],
        "last_scan": total["last"],
        "by_user_agent": [dict(r) for r in by_agent],
        "recent_scans": [dict(r) for r in recent],
    }
