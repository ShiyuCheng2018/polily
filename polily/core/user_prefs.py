"""User preferences K/V store backed by the `user_prefs` table.

Used for runtime-mutable settings that should persist across launches but
should NOT be written back to the YAML config file (which is user-edited).
First consumer: TUI language selection.

Contract:
- `get_pref(db, key)` returns the stored value or None (or `default` if given).
- `set_pref(db, key, value)` upserts and stamps `updated_at` (UTC ISO).
- `list_prefs(db)` returns a dict of all key→value pairs (small table; full scan is fine).
"""
from __future__ import annotations

from datetime import datetime, timezone

from polily.core.db import PolilyDB


def get_pref(db: PolilyDB, key: str, default: str | None = None) -> str | None:
    row = db.conn.execute(
        "SELECT value FROM user_prefs WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return default
    return row["value"] if hasattr(row, "keys") else row[0]


def set_pref(db: PolilyDB, key: str, value: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        """
        INSERT INTO user_prefs (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, now),
    )
    db.conn.commit()


def list_prefs(db: PolilyDB) -> dict[str, str]:
    rows = db.conn.execute("SELECT key, value FROM user_prefs").fetchall()
    return {r["key"]: r["value"] for r in rows}
