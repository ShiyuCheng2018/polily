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


# --- v0.12.0 Task 21: max_prompt_chars 5000 → 100000 migration ---


def test_max_prompt_chars_migration_bumps_old_default(tmp_path):
    """Existing v0.11.x DBs with seeded 5000 must auto-bump to 100000 on first
    v0.12.0 boot. The 5000 threshold triggered BaseAgent temp-file overflow on
    every v0.12.0 dispatch.
    """
    import json as _json

    from polily.core.config_store import _migrate_max_prompt_chars_v0_12_0

    db = PolilyDB(tmp_path / "polily.db")
    # Simulate v0.11.x state: write old default 5000 directly, bypassing seed.
    db.conn.execute(
        "INSERT OR REPLACE INTO config (key_path, value, updated_at) "
        "VALUES (?, ?, ?)",
        ("ai.narrative_writer.max_prompt_chars", _json.dumps(5000), "2026-01-01T00:00:00Z"),
    )
    db.conn.commit()

    bumped = _migrate_max_prompt_chars_v0_12_0(db)
    assert bumped is True

    row = db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'ai.narrative_writer.max_prompt_chars'"
    ).fetchone()
    assert _json.loads(row["value"]) == 100000


def test_max_prompt_chars_migration_idempotent_on_new_default(tmp_path):
    """If value is already 100000 (fresh v0.12.0 install), migration is no-op."""
    import json as _json

    from polily.core.config_store import _migrate_max_prompt_chars_v0_12_0

    db = PolilyDB(tmp_path / "polily.db")
    # Fresh v0.12.0: ensure_seeded already wrote 100000 from the new Pydantic default.
    db.conn.execute(
        "INSERT OR REPLACE INTO config (key_path, value, updated_at) "
        "VALUES (?, ?, ?)",
        ("ai.narrative_writer.max_prompt_chars", _json.dumps(100000), "2026-05-09T00:00:00Z"),
    )
    db.conn.commit()

    bumped = _migrate_max_prompt_chars_v0_12_0(db)
    assert bumped is False, "Migration should no-op when value is already 100000"

    row = db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'ai.narrative_writer.max_prompt_chars'"
    ).fetchone()
    assert _json.loads(row["value"]) == 100000


def test_max_prompt_chars_migration_preserves_user_custom_value(tmp_path):
    """If user has explicitly set a custom value (e.g., 50000), don't touch it."""
    import json as _json

    from polily.core.config_store import _migrate_max_prompt_chars_v0_12_0

    db = PolilyDB(tmp_path / "polily.db")
    db.conn.execute(
        "INSERT OR REPLACE INTO config (key_path, value, updated_at) "
        "VALUES (?, ?, ?)",
        ("ai.narrative_writer.max_prompt_chars", _json.dumps(50000), "2026-05-09T00:00:00Z"),
    )
    db.conn.commit()

    bumped = _migrate_max_prompt_chars_v0_12_0(db)
    assert bumped is False, "Migration must not overwrite a user-customized value"

    row = db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'ai.narrative_writer.max_prompt_chars'"
    ).fetchone()
    assert _json.loads(row["value"]) == 50000


def test_max_prompt_chars_fresh_install_seeds_new_default(tmp_path):
    """Fresh v0.12.0 install via PolilyDB() + ensure_seeded must seed 100000."""
    import json as _json

    from polily.core.config import load_config_from_db

    db = PolilyDB(tmp_path / "polily.db")
    cfg = load_config_from_db(db)
    assert cfg.ai.narrative_writer.max_prompt_chars == 100000

    row = db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'ai.narrative_writer.max_prompt_chars'"
    ).fetchone()
    assert _json.loads(row["value"]) == 100000


# --- v0.12.0 Task A4: default model sonnet → opus migration ---


def test_narrative_writer_model_migration_bumps_sonnet_to_opus(tmp_path):
    """Existing v0.11.x DBs with seeded 'sonnet' must auto-bump to 'opus' on
    first v0.12.0 boot. Reasoning: v0.12.0's analysis surface (multi-platform
    cross-checks, position management depth, conditional framing under
    uncertainty) benefits materially from Opus-tier reasoning, and the
    long-context Manual + Strategy + Protocol stack (~40 KB) is well within
    Opus 4.7's 1M token window. Sonnet remains explicitly settable.
    """
    import json as _json

    from polily.core.config_store import _migrate_narrative_writer_model_v0_12_0

    db = PolilyDB(tmp_path / "polily.db")
    db.conn.execute(
        "INSERT OR REPLACE INTO config (key_path, value, updated_at) "
        "VALUES (?, ?, ?)",
        ("ai.narrative_writer.model", _json.dumps("sonnet"), "2026-01-01T00:00:00Z"),
    )
    db.conn.commit()

    bumped = _migrate_narrative_writer_model_v0_12_0(db)
    assert bumped is True

    row = db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'ai.narrative_writer.model'"
    ).fetchone()
    assert _json.loads(row["value"]) == "opus"


def test_narrative_writer_model_migration_idempotent_on_opus(tmp_path):
    """If value is already 'opus' (fresh v0.12.0 install), migration is no-op."""
    import json as _json

    from polily.core.config_store import _migrate_narrative_writer_model_v0_12_0

    db = PolilyDB(tmp_path / "polily.db")
    db.conn.execute(
        "INSERT OR REPLACE INTO config (key_path, value, updated_at) "
        "VALUES (?, ?, ?)",
        ("ai.narrative_writer.model", _json.dumps("opus"), "2026-05-10T00:00:00Z"),
    )
    db.conn.commit()

    bumped = _migrate_narrative_writer_model_v0_12_0(db)
    assert bumped is False, "Migration should no-op when value is already opus"

    row = db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'ai.narrative_writer.model'"
    ).fetchone()
    assert _json.loads(row["value"]) == "opus"


def test_narrative_writer_model_migration_preserves_user_custom_value(tmp_path):
    """If user has explicitly set a custom model (e.g., 'haiku'), don't touch it.

    Migration only fires on the v0.11.x default ('sonnet') so users who
    deliberately downgraded for cost/speed keep their choice.
    """
    import json as _json

    from polily.core.config_store import _migrate_narrative_writer_model_v0_12_0

    db = PolilyDB(tmp_path / "polily.db")
    db.conn.execute(
        "INSERT OR REPLACE INTO config (key_path, value, updated_at) "
        "VALUES (?, ?, ?)",
        ("ai.narrative_writer.model", _json.dumps("haiku"), "2026-05-10T00:00:00Z"),
    )
    db.conn.commit()

    bumped = _migrate_narrative_writer_model_v0_12_0(db)
    assert bumped is False, "Migration must not overwrite a user-customized model"

    row = db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'ai.narrative_writer.model'"
    ).fetchone()
    assert _json.loads(row["value"]) == "haiku"


def test_position_event_id_drift_heals_on_boot(tmp_path):
    """v0.12.0 bug #1 root-fix: a one-shot heal migration runs on first
    v0.12.0 boot, re-syncing every positions.event_id to match the
    canonical markets.event_id. This eliminates the drift class
    entirely — every query (including SQL JOINs in service.py event-list
    queries that we don't directly fix) sees consistent data.

    Test reproduces drift by direct INSERT, calls load_config_from_db
    (which runs all migrations), asserts positions.event_id is now
    canonical.
    """
    from datetime import UTC, datetime

    from polily.core.config import load_config_from_db

    db = PolilyDB(tmp_path / "polily.db")
    now = datetime.now(UTC).isoformat()

    # Seed an event + market with canonical event_id='ev_canonical'
    db.conn.execute(
        "INSERT INTO events (event_id, title, updated_at) "
        "VALUES ('ev_canonical', 'E', ?)", (now,),
    )
    db.conn.execute(
        "INSERT INTO markets (market_id, event_id, question, updated_at) "
        "VALUES ('m_target', 'ev_canonical', 'Q', ?)", (now,),
    )
    # Insert a drifted position (event_id wrong)
    db.conn.execute(
        "INSERT INTO events (event_id, title, updated_at) "
        "VALUES ('ev_wrong', 'W', ?)", (now,),
    )
    db.conn.execute(
        "INSERT INTO positions (market_id, side, event_id, shares, avg_cost, "
        "cost_basis, realized_pnl, title, opened_at, updated_at) "
        "VALUES ('m_target', 'yes', 'ev_wrong', 10.0, 0.5, 5.0, 0.0, 'Q', ?, ?)",
        (now, now),
    )
    db.conn.commit()

    # Run migrations (load_config_from_db is the canonical entry point)
    load_config_from_db(db)

    # Heal should have fixed the drift
    row = db.conn.execute(
        "SELECT event_id FROM positions WHERE market_id='m_target' AND side='yes'"
    ).fetchone()
    assert row["event_id"] == "ev_canonical", (
        f"Drift not healed: positions.event_id={row['event_id']!r} "
        f"after migration; expected 'ev_canonical' (from markets.event_id)"
    )


def test_position_event_id_heal_is_idempotent_on_clean_data(tmp_path):
    """If positions.event_id already matches markets.event_id, the heal
    migration must be a no-op (0 rows updated). This is the typical
    state on fresh installs."""
    from datetime import UTC, datetime

    from polily.core.config import load_config_from_db

    db = PolilyDB(tmp_path / "polily.db")
    now = datetime.now(UTC).isoformat()
    db.conn.execute(
        "INSERT INTO events (event_id, title, updated_at) VALUES ('e1', 'E', ?)",
        (now,),
    )
    db.conn.execute(
        "INSERT INTO markets (market_id, event_id, question, updated_at) "
        "VALUES ('m1', 'e1', 'Q', ?)", (now,),
    )
    db.conn.execute(
        "INSERT INTO positions (market_id, side, event_id, shares, avg_cost, "
        "cost_basis, realized_pnl, title, opened_at, updated_at) "
        "VALUES ('m1', 'yes', 'e1', 5.0, 0.4, 2.0, 0.0, 'Q', ?, ?)",
        (now, now),
    )
    db.conn.commit()

    # Should run without errors and leave the row alone
    load_config_from_db(db)
    row = db.conn.execute(
        "SELECT event_id FROM positions WHERE market_id='m1'"
    ).fetchone()
    assert row["event_id"] == "e1"


def test_narrative_writer_model_fresh_install_seeds_opus(tmp_path):
    """Fresh v0.12.0 install via PolilyDB() + load_config_from_db must seed 'opus'."""
    import json as _json

    from polily.core.config import load_config_from_db

    db = PolilyDB(tmp_path / "polily.db")
    cfg = load_config_from_db(db)
    assert cfg.ai.narrative_writer.model == "opus"

    row = db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'ai.narrative_writer.model'"
    ).fetchone()
    assert _json.loads(row["value"]) == "opus"
