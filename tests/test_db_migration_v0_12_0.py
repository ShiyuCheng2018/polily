"""DB schema migrations introduced in v0.12.0."""
import json

import pytest

from polily.core.db import PolilyDB


def test_analyses_has_narrative_format_column(tmp_path):
    """v0.12.0 adds narrative_format column to analyses; default 'json' for legacy rows."""
    db = PolilyDB(tmp_path / "polily.db")
    cols = [r["name"] for r in db.conn.execute("PRAGMA table_info(analyses)").fetchall()]
    assert "narrative_format" in cols, "analyses must have narrative_format column"


def test_user_strategy_table_exists_with_single_row(tmp_path):
    """v0.12.0 adds user_strategy table; seeded with a single row id=1."""
    db = PolilyDB(tmp_path / "polily.db")
    rows = db.conn.execute("SELECT id, text, updated_at FROM user_strategy").fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert rows[0]["text"] == ""


def test_user_strategy_check_constraint_blocks_second_row(tmp_path):
    """CHECK (id = 1) constraint enforces single-slot."""
    import sqlite3
    db = PolilyDB(tmp_path / "polily.db")
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("INSERT INTO user_strategy (id, text, updated_at) VALUES (2, 'x', '')")


def test_active_strategy_config_knob_default_official(tmp_path):
    """active_strategy seeds as 'official' (JSON-encoded) on first
    load_config_from_db call. Per the polily contract, PolilyDB.__init__
    is DDL-only; config seeding happens via ensure_seeded which is
    invoked by load_config_from_db.
    """
    from polily.core.config import load_config_from_db

    db = PolilyDB(tmp_path / "polily.db")
    # PolilyDB.__init__ alone does NOT seed config (see test_db_seed.py).
    # active_strategy is seeded via the standard load_config_from_db path.
    config = load_config_from_db(db)
    assert config.active_strategy == "official"

    row = db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'active_strategy'"
    ).fetchone()
    assert row is not None
    # config.value is JSON-encoded — decode to compare
    assert json.loads(row["value"]) == "official"


def test_active_strategy_loads_through_config_store(tmp_path):
    """Verify the knob round-trips through the existing config_store API.

    Caller seeds via load_config_from_db (the canonical bootstrap path);
    load_all then surfaces the row.
    """
    from polily.core.config import load_config_from_db
    from polily.core.config_store import load_all

    db = PolilyDB(tmp_path / "polily.db")
    load_config_from_db(db)  # triggers ensure_seeded -> INSERT OR IGNORE
    cfg = load_all(db)
    assert cfg.get("active_strategy") == "official"


def test_legacy_analyses_get_json_format_on_migration(tmp_path):
    """Pre-existing analyses rows (simulated) get narrative_format='json' on migration."""
    db_path = tmp_path / "polily.db"
    db = PolilyDB(db_path)
    # analyses.event_id has a FK on events.event_id — seed the parent first.
    db.conn.execute(
        "INSERT INTO events (event_id, slug, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("evt1", "evt1-slug", "evt1 title",
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    db.conn.execute(
        """INSERT INTO analyses
            (event_id, version, created_at, trigger_source,
             prices_snapshot, narrative_output,
             structure_score, score_breakdown,
             mispricing_signal, mispricing_details, elapsed_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("evt1", 1, "2026-01-01T00:00:00Z", "manual",
         "{}", '{"summary": "old"}',
         85.0, '{"spread": 90}', "none", None, 12.5)
    )
    db.conn.commit()
    row = db.conn.execute(
        "SELECT narrative_format FROM analyses WHERE event_id = 'evt1' AND version = 1"
    ).fetchone()
    assert row["narrative_format"] == "json"
