"""Tests for the PolilyDB schema (DDL surface).

These tests assert structural invariants on the SQLite schema produced by
`PolilyDB._init_schema` — table existence, column shape, primary keys, etc.
They are intentionally separate from `test_db.py` (which exercises behavior)
so that schema regressions surface as crisp DDL-level failures.
"""


def test_config_table_exists_after_init(polily_db):
    """config table created with key_path PK + value TEXT + updated_at TEXT."""
    cur = polily_db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='config'"
    )
    assert cur.fetchone() is not None, "config table missing from schema"

    cur = polily_db.conn.execute("PRAGMA table_info(config)")
    cols = {row[1]: row[2] for row in cur.fetchall()}
    assert cols == {
        "key_path": "TEXT",
        "value": "TEXT",
        "updated_at": "TEXT",
    }, f"unexpected columns: {cols}"

    # Verify key_path is PRIMARY KEY
    cur = polily_db.conn.execute("PRAGMA table_info(config)")
    pk_cols = [row[1] for row in cur.fetchall() if row[5] == 1]
    assert pk_cols == ["key_path"], f"expected key_path PK, got {pk_cols}"
