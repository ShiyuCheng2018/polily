"""Strategy store — single source of truth for active-strategy resolution.

Reads/writes user_strategy table + active_strategy config knob. Loads
packaged default.md for the 'official' branch. Empty user_strategy.text
is returned literally (the agent self-falls-back via Read tool per
manual.md §7).

active_strategy config knob is read/written through the existing
`polily.core.config_store` API (load_all / upsert) so it participates
in PolilyConfig validation + JSON encoding consistently with every other
config knob. Raw INSERT into the `config` table would bypass the
allowlist check and serializer.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polily
from polily.core.config_store import load_all, upsert
from polily.core.db import PolilyDB


def get_active_strategy_name(db: PolilyDB) -> str:
    """Return 'official' or 'user' from config (via config_store)."""
    cfg = load_all(db)
    return cfg.get("active_strategy", "official")


def set_active_strategy(db: PolilyDB, value: str) -> None:
    """Validate and write config.active_strategy via config_store.upsert.

    upsert validates `value` against PolilyConfig.active_strategy
    (Literal["official", "user"]) and JSON-encodes; raises on invalid value.
    """
    if value not in ("official", "user"):
        raise ValueError(f"Invalid active_strategy value: {value!r}")
    upsert(db, "active_strategy", value)


def get_user_strategy_text(db: PolilyDB) -> str:
    """Return the user's saved strategy text (may be '')."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT text FROM user_strategy WHERE id = 1"
        ).fetchone()
    return row["text"] if row else ""


def save_user_strategy(db: PolilyDB, text: str) -> None:
    """Overwrite user_strategy.text + bump updated_at."""
    now = datetime.now(UTC).isoformat()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE user_strategy SET text = ?, updated_at = ? WHERE id = 1",
            (text, now),
        )


def load_official_strategy() -> str:
    """Read packaged default.md."""
    return (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")


def get_active_strategy_text(db: PolilyDB) -> str:
    """Return the strategy text for prompt injection.

    'official' → packaged default.md
    'user'     → user_strategy.text (literal; '' is allowed — agent falls
                  back via Read tool per manual.md §7)
    """
    if get_active_strategy_name(db) == "official":
        return load_official_strategy()
    return get_user_strategy_text(db)
