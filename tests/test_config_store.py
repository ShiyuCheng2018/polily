"""Unit tests for polily.core.config_store."""
from __future__ import annotations

from polily.core.config_store import EPHEMERAL_FIELDS


def test_ephemeral_fields_contains_user_agent():
    """api.user_agent is the only known EPHEMERAL field (per Q3 / design §3.2)."""
    assert "api.user_agent" in EPHEMERAL_FIELDS


def test_ephemeral_fields_is_frozenset():
    """frozenset enforces immutability — can't be mutated at runtime."""
    assert isinstance(EPHEMERAL_FIELDS, frozenset)


from polily.core.config_store import (
    TERRITORY_A_PREFIXES,
    is_territory_a,
)


def test_territory_a_prefixes_covers_4_user_facing_sections():
    """Per Q1 — only 4 sections are TUI-editable."""
    assert TERRITORY_A_PREFIXES == (
        "movement.",
        "scoring.thresholds.",
        "mispricing.",
        "wallet.",
    )


def test_is_territory_a_recognizes_movement_keys():
    assert is_territory_a("movement.magnitude_threshold") is True
    assert is_territory_a("movement.weights.crypto.magnitude.price_z_score") is True


def test_is_territory_a_excludes_hidden_sections():
    """api.* / tui.* / ai.* / archiving.* are HIDDEN_IN_TUI per Q1."""
    assert is_territory_a("api.request_timeout_seconds") is False
    assert is_territory_a("tui.heartbeat_seconds") is False
    assert is_territory_a("ai.narrative_writer.model") is False
    assert is_territory_a("archiving.db_file") is False


def test_is_territory_a_excludes_ephemeral_fields():
    """api.user_agent is EPHEMERAL — never editable via TUI."""
    assert is_territory_a("api.user_agent") is False


def test_territory_a_prefixes_top_levels_align_with_pydantic_schema():
    """Schema drift guard — if PolilyConfig adds a top-level section,
    either add it to TERRITORY_A_PREFIXES (visible) or to
    _HIDDEN_TOP_LEVELS (intentionally hidden). Forces conscious choice."""
    from polily.core.config import PolilyConfig
    pydantic_top = set(PolilyConfig.model_fields.keys())
    territory_top = {p.split(".")[0] for p in TERRITORY_A_PREFIXES}
    hidden_top = {"api", "tui", "ai", "archiving"}
    assert territory_top | hidden_top == pydantic_top, (
        f"PolilyConfig schema drift: section appeared/disappeared.\n"
        f"  pydantic top-level: {sorted(pydantic_top)}\n"
        f"  territory_a:        {sorted(territory_top)}\n"
        f"  hidden:             {sorted(hidden_top)}\n"
        f"  unaccounted:        {sorted(pydantic_top - territory_top - hidden_top)}"
    )


from polily.core.config import PolilyConfig
from polily.core.config_store import _flatten_pydantic


def test_flatten_pydantic_scalar_leaves():
    """Top-level scalars become dot-notation keys."""
    flat = _flatten_pydantic(PolilyConfig())
    assert flat["movement.magnitude_threshold"] == 70
    assert flat["movement.quality_threshold"] == 60
    assert flat["wallet.starting_balance"] == 100.0
    assert flat["api.request_timeout_seconds"] == 20


def test_flatten_pydantic_nested_dict_of_basemodel():
    """movement.weights[type] dict-of-MovementWeights flattens to leaves."""
    flat = _flatten_pydantic(PolilyConfig())
    # Per design §12.A.2 — 26 weights leaves
    assert flat["movement.weights.crypto.magnitude.price_z_score"] == 0.15
    assert flat["movement.weights.political.magnitude.sustained_drift"] == 0.40
    assert flat["movement.weights.default.quality.volume_ratio"] == 0.40


def test_flatten_pydantic_includes_ephemeral_fields():
    """_flatten_pydantic returns ALL leaves; EPHEMERAL filtering happens
    at seed/save/load layers, not at flatten."""
    flat = _flatten_pydantic(PolilyConfig())
    assert "api.user_agent" in flat


def test_flatten_pydantic_total_leaf_count_is_47():
    """Locks the 47-leaf invariant from design §3.2.

    If this fails the schema changed — update the design doc + this test
    together (and audit territory A whitelist before continuing).
    """
    flat = _flatten_pydantic(PolilyConfig())
    assert len(flat) == 47, f"expected 47 leaves, got {len(flat)}: {sorted(flat.keys())}"


from polily.core.config_store import _unflatten


def test_unflatten_scalar_leaves():
    flat = {
        "movement.magnitude_threshold": 50,
        "wallet.starting_balance": 200.0,
    }
    nested = _unflatten(flat)
    assert nested == {
        "movement": {"magnitude_threshold": 50},
        "wallet": {"starting_balance": 200.0},
    }


def test_unflatten_deeply_nested_weights():
    flat = {
        "movement.weights.crypto.magnitude.price_z_score": 0.15,
        "movement.weights.crypto.magnitude.book_imbalance": 0.10,
        "movement.weights.crypto.quality.volume_ratio": 0.40,
    }
    nested = _unflatten(flat)
    assert nested == {
        "movement": {
            "weights": {
                "crypto": {
                    "magnitude": {
                        "price_z_score": 0.15,
                        "book_imbalance": 0.10,
                    },
                    "quality": {"volume_ratio": 0.40},
                },
            },
        },
    }


def test_flatten_then_unflatten_roundtrips():
    """flatten → unflatten → model_validate must equal original PolilyConfig."""
    original = PolilyConfig()
    flat = _flatten_pydantic(original)
    nested = _unflatten(flat)
    rebuilt = PolilyConfig.model_validate(nested)
    assert rebuilt.model_dump() == original.model_dump()


import json
from polily.core.config_store import ensure_seeded


def test_ensure_seeded_populates_empty_db(polily_db):
    """First-run seed inserts 46 rows (47 leaves minus 1 EPHEMERAL)."""
    ensure_seeded(polily_db)

    cur = polily_db.conn.execute("SELECT COUNT(*) FROM config")
    count = cur.fetchone()[0]
    assert count == 46, f"expected 46 rows (47 - 1 ephemeral), got {count}"


def test_ensure_seeded_skips_ephemeral_fields(polily_db):
    """api.user_agent must NOT appear in db.config — it's runtime-computed."""
    ensure_seeded(polily_db)

    cur = polily_db.conn.execute(
        "SELECT key_path FROM config WHERE key_path = 'api.user_agent'"
    )
    assert cur.fetchone() is None, "api.user_agent should not be persisted"


def test_ensure_seeded_stores_values_as_json(polily_db):
    """Values are JSON-encoded so types round-trip cleanly."""
    ensure_seeded(polily_db)

    cur = polily_db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'movement.magnitude_threshold'"
    )
    raw = cur.fetchone()[0]
    assert json.loads(raw) == 70

    cur = polily_db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'mispricing.enabled'"
    )
    assert json.loads(cur.fetchone()[0]) is True


def test_ensure_seeded_is_idempotent(polily_db):
    """Running ensure_seeded twice doesn't duplicate rows."""
    ensure_seeded(polily_db)
    ensure_seeded(polily_db)
    cur = polily_db.conn.execute("SELECT COUNT(*) FROM config")
    assert cur.fetchone()[0] == 46


def test_ensure_seeded_does_not_overwrite_user_edited_value(polily_db):
    """If user already changed a leaf, ensure_seeded leaves it alone (INSERT OR IGNORE)."""
    ensure_seeded(polily_db)

    # Simulate user TUI edit: set magnitude_threshold to 50
    polily_db.conn.execute(
        "UPDATE config SET value = ? WHERE key_path = ?",
        (json.dumps(50), "movement.magnitude_threshold"),
    )
    polily_db.conn.commit()

    # Re-seed (e.g., next polily startup)
    ensure_seeded(polily_db)

    # User's 50 must survive
    cur = polily_db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'movement.magnitude_threshold'"
    )
    assert json.loads(cur.fetchone()[0]) == 50, "user-edited value was overwritten"


def test_ensure_seeded_restores_user_deleted_row(polily_db):
    """If user deletes a row via raw SQL, next ensure_seeded re-adds default."""
    ensure_seeded(polily_db)
    polily_db.conn.execute(
        "DELETE FROM config WHERE key_path = ?",
        ("movement.magnitude_threshold",),
    )
    polily_db.conn.commit()

    ensure_seeded(polily_db)

    cur = polily_db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'movement.magnitude_threshold'"
    )
    assert json.loads(cur.fetchone()[0]) == 70  # back to Pydantic default


def test_ensure_seeded_safe_under_concurrent_threads_each_with_own_connection(tmp_path):
    """Whis SF5 (rewritten) — 4 threads each open their own PolilyDB
    instance and call ensure_seeded concurrently.

    Why per-thread connection: Python's sqlite3 module serializes
    transactions per connection regardless of check_same_thread=False;
    sharing one connection across threads in `with conn:` blocks raises
    InterfaceError. The realistic concurrency scenario in polily is
    "TUI process and daemon process race during first startup" —
    different processes, different connections, but same db file.
    This test simulates that with 4 concurrent threads × own connection,
    relying on OS-level fcntl + INSERT OR IGNORE for safety.
    """
    import threading
    from polily.core.db import PolilyDB

    db_path = tmp_path / "polily.db"
    errors = []

    def worker():
        db = PolilyDB(db_path)
        try:
            ensure_seeded(db)
        except Exception as e:
            errors.append(e)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"ensure_seeded raised under concurrent threads: {errors}"
    # Verify final state: exactly 46 rows, no duplicates
    db = PolilyDB(db_path)
    try:
        cur = db.conn.execute("SELECT COUNT(*) FROM config")
        assert cur.fetchone()[0] == 46
    finally:
        db.close()


def test_ensure_seeded_safe_across_independent_db_connections(tmp_path):
    """Whis SF6 — TUI process + daemon process opening separate
    PolilyDB instances on the same db file (real cross-process scenario).

    Simulated within one Python process by opening two PolilyDB instances;
    OS-level fcntl locking + INSERT OR IGNORE handles the race.

    Note: this test imports load_all from config_store. As of T1.6 commit
    time, load_all has NOT been implemented yet (lands in T1.7). Until
    then, this test fails on import. That's intentional — when T1.7
    lands, the test will pass without changes. Acceptable per plan.
    """
    from polily.core.db import PolilyDB
    from polily.core.config_store import load_all

    db_path = tmp_path / "polily.db"
    db_a = PolilyDB(db_path)
    db_b = PolilyDB(db_path)
    try:
        # Both call ensure_seeded; second should be a no-op (rows already
        # exist from first INSERT OR IGNORE)
        ensure_seeded(db_a)
        ensure_seeded(db_b)

        cur = db_b.conn.execute("SELECT COUNT(*) FROM config")
        assert cur.fetchone()[0] == 46  # not 92 (no duplicates)

        # Both connections see the same data
        flat_a = load_all(db_a)
        flat_b = load_all(db_b)
        assert flat_a == flat_b
    finally:
        db_a.close()
        db_b.close()


from datetime import UTC, datetime

from polily.core.config_store import load_all


def test_load_all_returns_dict_keyed_by_key_path(polily_db):
    ensure_seeded(polily_db)
    flat = load_all(polily_db)
    assert isinstance(flat, dict)
    assert flat["movement.magnitude_threshold"] == 70
    assert flat["wallet.starting_balance"] == 100.0
    assert flat["mispricing.enabled"] is True


def test_load_all_decodes_json_values(polily_db):
    """Values stored as JSON strings round-trip through json.loads."""
    ensure_seeded(polily_db)
    flat = load_all(polily_db)
    # bool / int / float / str must come back as proper Python types
    assert isinstance(flat["mispricing.enabled"], bool)
    assert isinstance(flat["movement.daily_analysis_limit"], int)
    assert isinstance(flat["wallet.starting_balance"], float)
    assert isinstance(flat["ai.narrative_writer.model"], str)


def test_load_all_excludes_ephemeral_fields_even_if_present(polily_db):
    """Defense-in-depth: even if user inserts api.user_agent via raw SQL,
    load_all filters it out so PolilyConfig's default_factory wins."""
    ensure_seeded(polily_db)
    polily_db.conn.execute(
        "INSERT INTO config VALUES (?, ?, ?)",
        ("api.user_agent", json.dumps("polily/EVIL-1.0"), datetime.now(UTC).isoformat()),
    )
    polily_db.conn.commit()

    flat = load_all(polily_db)
    assert "api.user_agent" not in flat, "EPHEMERAL fields must be filtered out"


def test_load_all_returns_empty_dict_for_unseeded_db(polily_db):
    flat = load_all(polily_db)
    assert flat == {}


import pytest
from polily.core.config_store import ConfigSaveError, upsert


def test_upsert_writes_new_row_for_existing_key(polily_db):
    """Update existing seeded row."""
    ensure_seeded(polily_db)
    upsert(polily_db, "movement.magnitude_threshold", 50)

    flat = load_all(polily_db)
    assert flat["movement.magnitude_threshold"] == 50


def test_upsert_updates_updated_at(polily_db):
    """updated_at column refreshes on each upsert."""
    ensure_seeded(polily_db)
    cur = polily_db.conn.execute(
        "SELECT updated_at FROM config WHERE key_path = ?",
        ("movement.magnitude_threshold",),
    )
    initial = cur.fetchone()[0]

    import time
    time.sleep(0.01)
    upsert(polily_db, "movement.magnitude_threshold", 50)

    cur = polily_db.conn.execute(
        "SELECT updated_at FROM config WHERE key_path = ?",
        ("movement.magnitude_threshold",),
    )
    after = cur.fetchone()[0]
    assert after > initial


def test_upsert_rejects_ephemeral_field(polily_db):
    """api.user_agent cannot be persisted — would defeat default_factory."""
    ensure_seeded(polily_db)
    with pytest.raises(ConfigSaveError, match="api.user_agent"):
        upsert(polily_db, "api.user_agent", "polily/HACK")


def test_upsert_serializes_complex_value_as_json(polily_db):
    """List / dict values stored as JSON strings."""
    ensure_seeded(polily_db)
    # No list-typed leaves in territory A as of v0.9.5, but the helper
    # must round-trip them anyway to be future-proof.
    upsert(polily_db, "movement.magnitude_threshold", 60.5)
    flat = load_all(polily_db)
    assert flat["movement.magnitude_threshold"] == 60.5


from polily.core.config_store import reset


def test_reset_writes_pydantic_default(polily_db):
    """reset(key) writes the current PolilyConfig default value."""
    ensure_seeded(polily_db)
    upsert(polily_db, "movement.magnitude_threshold", 50)

    reset(polily_db, "movement.magnitude_threshold")

    flat = load_all(polily_db)
    assert flat["movement.magnitude_threshold"] == 70


def test_reset_works_for_deeply_nested_weight(polily_db):
    """reset works for arbitrary depth (movement.weights.crypto.magnitude.price_z_score)."""
    ensure_seeded(polily_db)
    upsert(polily_db, "movement.weights.crypto.magnitude.price_z_score", 0.99)

    reset(polily_db, "movement.weights.crypto.magnitude.price_z_score")

    flat = load_all(polily_db)
    assert flat["movement.weights.crypto.magnitude.price_z_score"] == 0.15


def test_reset_rejects_ephemeral_field(polily_db):
    ensure_seeded(polily_db)
    with pytest.raises(ConfigSaveError, match="api.user_agent"):
        reset(polily_db, "api.user_agent")


def test_reset_rejects_unknown_key(polily_db):
    """Unknown key_path raises clearly instead of silently no-op'ing."""
    ensure_seeded(polily_db)
    with pytest.raises(KeyError, match="movement.does_not_exist"):
        reset(polily_db, "movement.does_not_exist")


def test_migrate_yaml_imports_existing_user_values(polily_db, tmp_path, monkeypatch):
    """Pre-v0.10.0 users with custom config.yaml — values get imported."""
    monkeypatch.chdir(tmp_path)
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "wallet:\n"
        "  starting_balance: 250.0\n"
        "movement:\n"
        "  magnitude_threshold: 55\n",
        encoding="utf-8",
    )

    from polily.core.config_store import _migrate_yaml_to_db, load_all
    _migrate_yaml_to_db(polily_db)

    flat = load_all(polily_db)
    assert flat["wallet.starting_balance"] == 250.0
    assert flat["movement.magnitude_threshold"] == 55


def test_migrate_yaml_skips_when_db_already_populated(polily_db, tmp_path, monkeypatch):
    """Idempotent — once db.config has rows, migration is a no-op."""
    monkeypatch.chdir(tmp_path)
    from polily.core.config_store import (
        _migrate_yaml_to_db,
        ensure_seeded,
        load_all,
        upsert,
    )
    ensure_seeded(polily_db)
    upsert(polily_db, "wallet.starting_balance", 100.0)  # canonical value

    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "wallet:\n  starting_balance: 999.0\n", encoding="utf-8",
    )
    _migrate_yaml_to_db(polily_db)

    flat = load_all(polily_db)
    # User's existing 100.0 must NOT be overwritten by yaml's 999.0
    assert flat["wallet.starting_balance"] == 100.0


def test_migrate_yaml_skips_when_no_yaml_file(polily_db, tmp_path, monkeypatch):
    """Fresh install path — no yaml exists, no-op."""
    monkeypatch.chdir(tmp_path)
    from polily.core.config_store import _migrate_yaml_to_db, load_all
    _migrate_yaml_to_db(polily_db)
    assert load_all(polily_db) == {}  # still empty


def test_migrate_yaml_skips_ephemeral_fields(polily_db, tmp_path, monkeypatch):
    """Even if yaml has api.user_agent, EPHEMERAL filter rejects it."""
    monkeypatch.chdir(tmp_path)
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "api:\n  user_agent: polily/EVIL\n", encoding="utf-8",
    )
    from polily.core.config_store import _migrate_yaml_to_db, load_all
    _migrate_yaml_to_db(polily_db)
    flat = load_all(polily_db)
    assert "api.user_agent" not in flat


def test_migrate_yaml_handles_malformed_yaml_gracefully(polily_db, tmp_path, monkeypatch):
    """Garbled yaml shouldn't crash polily startup — just log and skip."""
    monkeypatch.chdir(tmp_path)
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(":: this is not yaml ::", encoding="utf-8")
    from polily.core.config_store import _migrate_yaml_to_db
    _migrate_yaml_to_db(polily_db)  # should not raise
