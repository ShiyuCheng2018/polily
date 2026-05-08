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
    """Pre-existing analyses rows (genuinely written WITHOUT narrative_format)
    get narrative_format='json' applied by the v0.12.0 ALTER TABLE migration.

    This exercises the actual upgrade path: a v0.11.x DB has analyses rows
    where the narrative_format column doesn't exist; v0.12.0 first-init
    runs ALTER + DEFAULT 'json'; existing rows are populated by the DEFAULT
    clause. Critical for users upgrading from v0.11.x — their full history
    must keep rendering after the column is added.
    """
    import sqlite3 as _sqlite3

    db_path = tmp_path / "polily.db"
    # Simulate a v0.11.x DB: open PolilyDB once to materialize the v0.12.0
    # schema, then DROP the narrative_format column to roll back to the
    # v0.11.x shape, INSERT a legacy row, close. SQLite doesn't have
    # DROP COLUMN before 3.35; we use the canonical "rebuild table without
    # the column" pattern. This keeps the events / index / FK shape
    # identical to v0.11.x — only the analyses-narrative_format column
    # differs.
    PolilyDB(db_path).conn.close()  # bring schema to v0.12.0
    conn = _sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript("""
        BEGIN;
        CREATE TABLE _analyses_v11 (
            event_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            trigger_source TEXT NOT NULL DEFAULT 'manual',
            prices_snapshot TEXT,
            narrative_output TEXT,
            structure_score REAL,
            score_breakdown TEXT,
            mispricing_signal TEXT NOT NULL DEFAULT 'none',
            mispricing_details TEXT,
            elapsed_seconds REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (event_id, version)
        );
        DROP TABLE analyses;
        ALTER TABLE _analyses_v11 RENAME TO analyses;
        COMMIT;
    """)
    # Insert a legacy row directly (FK off — events row not required for this test).
    conn.execute(
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
    conn.commit()
    # Sanity check: column does not exist BEFORE the migration runs.
    cols_before = [r[1] for r in conn.execute("PRAGMA table_info(analyses)").fetchall()]
    assert "narrative_format" not in cols_before, (
        "Test setup failed — narrative_format should be absent in simulated v0.11.x DB"
    )
    conn.close()

    # Re-open via PolilyDB — _init_schema's ALTER TABLE migration runs here
    # and populates the legacy row's narrative_format from the DEFAULT clause.
    db = PolilyDB(db_path)
    cols_after = [r["name"] for r in db.conn.execute("PRAGMA table_info(analyses)").fetchall()]
    assert "narrative_format" in cols_after
    row = db.conn.execute(
        "SELECT narrative_format FROM analyses WHERE event_id = 'evt1' AND version = 1"
    ).fetchone()
    assert row["narrative_format"] == "json", (
        "Legacy row should be auto-populated with default 'json' by ALTER's DEFAULT clause"
    )
