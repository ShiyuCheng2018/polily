"""Tests for SF1 — yaml→db migration visibility (AC2).

Reviewer flagged: in v0.9.x → v0.10.0 upgrade, if the user's legacy
config.yaml has a value that fails Pydantic validation, the migration
silently aborts and Pydantic defaults clobber the file on next yaml
regen — user loses customizations with no message.

The fix introduces:
1. `_migrate_yaml_to_db` returns a structured status (instead of just logging)
2. CLI bootstrap surfaces the status to stderr so the user sees it
3. Invalid-yaml case renames `config.yaml` → `config.yaml.bak` so the user
   can manually rescue values
"""
from __future__ import annotations

from polily.core.config_store import _migrate_yaml_to_db
from polily.core.db import PolilyDB


def test_migrate_returns_ok_with_count_when_yaml_present(tmp_path, monkeypatch):
    """Happy path: legacy yaml present, all values valid → status 'ok'."""
    monkeypatch.chdir(tmp_path)
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "wallet:\n  starting_balance: 250.0\n", encoding="utf-8",
    )
    db = PolilyDB(tmp_path / "polily.db")
    # Strip the auto-seed that PolilyDB.__init__ may have done so the
    # migration's empty-table precondition holds (matches the real
    # v0.9.x → v0.10.0 upgrade case).
    db.conn.execute("DELETE FROM config")
    db.conn.commit()
    try:
        status = _migrate_yaml_to_db(db)
        assert status[0] == "ok"
        assert isinstance(status[1], int)
        assert status[1] > 0  # several leaves migrated
    finally:
        db.close()


def test_migrate_returns_skipped_no_yaml_when_fresh_install(tmp_path, monkeypatch):
    """Fresh install: no config.yaml → status 'skipped_no_yaml' (silent case)."""
    monkeypatch.chdir(tmp_path)
    db = PolilyDB(tmp_path / "polily.db")
    db.conn.execute("DELETE FROM config")
    db.conn.commit()
    try:
        status = _migrate_yaml_to_db(db)
        assert status == ("skipped_no_yaml",)
    finally:
        db.close()


def test_migrate_returns_skipped_invalid_and_renames_bak(tmp_path, monkeypatch):
    """Invalid yaml: status 'skipped_invalid' AND config.yaml.bak created.

    This is the AC2-critical case — without the .bak rescue, the next
    polily startup would yaml-regen over the user's customizations.
    """
    monkeypatch.chdir(tmp_path)
    yaml_path = tmp_path / "config.yaml"
    # wallet.starting_balance has Field(ge=1.0); 0.0 fails validation.
    yaml_path.write_text(
        "wallet:\n  starting_balance: 0.0\n", encoding="utf-8",
    )
    db = PolilyDB(tmp_path / "polily.db")
    db.conn.execute("DELETE FROM config")
    db.conn.commit()
    try:
        status = _migrate_yaml_to_db(db)
        assert status[0] == "skipped_invalid"
        # The reason should be a non-empty string (Pydantic ValidationError repr)
        assert isinstance(status[1], str) and status[1]
    finally:
        db.close()

    # The .bak rescue must have happened so the next startup's yaml regen
    # doesn't silently overwrite the user's customizations.
    assert not yaml_path.exists(), "original config.yaml should be renamed to .bak"
    bak_path = tmp_path / "config.yaml.bak"
    assert bak_path.exists(), "expected config.yaml.bak rescue file"
    # Content preserved verbatim
    assert "starting_balance: 0.0" in bak_path.read_text(encoding="utf-8")


def test_migrate_skips_when_db_already_seeded(tmp_path, monkeypatch):
    """Sentinel case: db.config already has rows → status 'skipped_already_migrated'.

    This is the idempotent re-run case (every polily startup after the first).
    """
    monkeypatch.chdir(tmp_path)
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "wallet:\n  starting_balance: 250.0\n", encoding="utf-8",
    )
    db = PolilyDB(tmp_path / "polily.db")
    # Simulate an already-seeded db.config (the post-first-startup state).
    # PolilyDB.__init__ no longer auto-seeds config (B2/v0.10.0), so we
    # invoke ensure_seeded explicitly.
    from polily.core.config_store import ensure_seeded
    ensure_seeded(db)
    try:
        status = _migrate_yaml_to_db(db)
        assert status == ("skipped_already_migrated",)
    finally:
        db.close()


def test_cli_emits_localized_message_on_ok(tmp_path, monkeypatch):
    """`polily config status` (or any cmd that bootstraps) prints migration result.

    We use `polily config reset --all --yes` because it's a fast bootstrap
    path that triggers config loading; the migration banner should appear
    on stderr if a migration just happened.
    """
    monkeypatch.chdir(tmp_path)
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "wallet:\n  starting_balance: 250.0\n", encoding="utf-8",
    )

    from polily.cli import _emit_migration_status_to_stderr

    # Run a migration first by loading
    from polily.core.config import load_config_from_db
    db = PolilyDB(tmp_path / "polily.db")
    db.conn.execute("DELETE FROM config")
    db.conn.commit()
    load_config_from_db(db)
    db.close()
    # Now: a separate emit call with a fresh db should see "already migrated"
    # because the prior load wrote rows. We test the OK message directly via
    # the helper's status arg path:
    import io
    import sys
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    _emit_migration_status_to_stderr(("ok", 7))
    output = buf.getvalue()
    assert "已迁移" in output
    assert "7" in output
    assert "config.yaml" in output


def test_cli_emits_localized_warning_on_invalid(tmp_path, monkeypatch):
    """When migration aborts due to invalid yaml, CLI prints a warning to stderr
    pointing the user at .bak.
    """
    import io
    import sys

    from polily.cli import _emit_migration_status_to_stderr

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    _emit_migration_status_to_stderr(
        ("skipped_invalid", "wallet.starting_balance must be >= 1.0"),
    )
    output = buf.getvalue()
    assert "校验失败" in output or "invalid" in output.lower()
    assert "config.yaml.bak" in output


def test_cli_silent_on_no_yaml(tmp_path, monkeypatch):
    """Fresh install: no config.yaml means we shouldn't spam stderr."""
    import io
    import sys

    from polily.cli import _emit_migration_status_to_stderr

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    _emit_migration_status_to_stderr(("skipped_no_yaml",))
    assert buf.getvalue() == ""


def test_cli_silent_on_already_migrated(tmp_path, monkeypatch):
    """Idempotent re-run: every polily startup after the first should be silent."""
    import io
    import sys

    from polily.cli import _emit_migration_status_to_stderr

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    _emit_migration_status_to_stderr(("skipped_already_migrated",))
    assert buf.getvalue() == ""


# --- get_last_migration_status: consume-and-clear semantics ---------------
#
# The status global is overwritten on every _migrate_yaml_to_db call.
# If a future caller chains two `load_config_from_db` invocations
# before emitting (or a test does setup-load + body-load without an
# emit between them), the first call's status would be silently
# clobbered. Pin the consume-and-clear contract so any double-read is
# a None instead of a stale repeat, and any back-to-back migration
# overwrites cleanly without leaking state from the previous pass.


def test_get_last_migration_status_consume_and_clear(tmp_path, monkeypatch):
    """Each migration produces exactly one status; getter clears after read."""
    monkeypatch.chdir(tmp_path)
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "wallet:\n  starting_balance: 250.0\n", encoding="utf-8",
    )
    db = PolilyDB(tmp_path / "polily.db")
    db.conn.execute("DELETE FROM config")
    db.conn.commit()
    try:
        _migrate_yaml_to_db(db)
    finally:
        db.close()

    from polily.core.config_store import get_last_migration_status

    first = get_last_migration_status()
    assert first is not None
    assert first[0] == "ok"

    # Second read without a new migration: must be None, not a repeat.
    assert get_last_migration_status() is None


def test_get_last_migration_status_resets_between_migrations(
    tmp_path, monkeypatch,
):
    """A second migration replaces the first status (no carry-over)."""
    # First migration: ok status
    yaml_path1 = tmp_path / "first" / "config.yaml"
    yaml_path1.parent.mkdir()
    yaml_path1.write_text(
        "wallet:\n  starting_balance: 250.0\n", encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path / "first")
    db = PolilyDB(tmp_path / "first" / "polily.db")
    db.conn.execute("DELETE FROM config")
    db.conn.commit()
    try:
        _migrate_yaml_to_db(db)
    finally:
        db.close()

    from polily.core.config_store import get_last_migration_status

    # Consume the first status without checking again — simulates a
    # caller that reads-and-acts. After consume, global is None.
    assert get_last_migration_status() is not None
    assert get_last_migration_status() is None

    # Second migration in a fresh dir: must produce its own status,
    # NOT carry "ok" from the previous run.
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    monkeypatch.chdir(second_dir)
    db2 = PolilyDB(second_dir / "polily.db")
    db2.conn.execute("DELETE FROM config")
    db2.conn.commit()
    try:
        _migrate_yaml_to_db(db2)  # no yaml in this dir → skipped_no_yaml
    finally:
        db2.close()

    second = get_last_migration_status()
    assert second == ("skipped_no_yaml",)
    # And it clears too
    assert get_last_migration_status() is None
