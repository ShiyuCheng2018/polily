"""Tests for reset_wallet — wipes wallet-side state while preserving
events/markets/analyses."""

import pytest

from polily.core.db import PolilyDB
from polily.core.wallet_reset import reset_wallet


def _seed_event_and_market(db, event_id="e1", market_id="m1"):
    db.conn.execute(
        "INSERT OR IGNORE INTO events (event_id,title,updated_at) VALUES (?,?,?)",
        (event_id, "E", "t"),
    )
    db.conn.execute(
        "INSERT OR IGNORE INTO markets (market_id,event_id,question,updated_at) "
        "VALUES (?,?,?,?)",
        (market_id, event_id, "Q", "t"),
    )
    db.conn.commit()


# --- core wipe + re-seed behavior ----------------------------------------


def test_reset_wipes_positions(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    _seed_event_and_market(db)
    db.conn.execute(
        """INSERT INTO positions
           (market_id,side,event_id,shares,avg_cost,cost_basis,title,opened_at,updated_at)
           VALUES ('m1','yes','e1',10,0.5,5,'Q','t','t')""",
    )
    db.conn.commit()
    reset_wallet(db, starting_balance=100.0)
    assert db.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0


def test_reset_wipes_wallet_transactions(tmp_path):
    """All ledger rows cleared — no bookmark protection needed now that
    migration is gone."""
    db = PolilyDB(tmp_path / "t.db")
    _seed_event_and_market(db)
    db.conn.execute(
        "INSERT INTO wallet_transactions (created_at,type,amount_usd,balance_after) "
        "VALUES (?,?,?,?)",
        ("2026-01-01", "TOPUP", 50.0, 150.0),
    )
    db.conn.commit()
    reset_wallet(db, starting_balance=100.0)
    assert db.conn.execute("SELECT COUNT(*) FROM wallet_transactions").fetchone()[0] == 0


def test_reset_preserves_events_markets(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    _seed_event_and_market(db)
    reset_wallet(db, starting_balance=100.0)
    assert db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0] == 1


def test_reset_reseeds_wallet_at_starting_balance(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    db.conn.execute("UPDATE wallet SET cash_usd=5, topup_total=50, withdraw_total=10 WHERE id=1")
    db.conn.commit()
    reset_wallet(db, starting_balance=250.0)
    row = db.conn.execute("SELECT * FROM wallet WHERE id=1").fetchone()
    assert row["cash_usd"] == 250.0
    assert row["starting_balance"] == 250.0
    assert row["topup_total"] == 0
    assert row["withdraw_total"] == 0


def test_reset_is_idempotent(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    reset_wallet(db, starting_balance=100.0)
    reset_wallet(db, starting_balance=100.0)  # no crash, no duplication
    row = db.conn.execute("SELECT COUNT(*) FROM wallet").fetchone()[0]
    assert row == 1


# --- validation -----------------------------------------------------------


def test_reset_rejects_non_positive_balance(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    with pytest.raises(ValueError, match="starting_balance"):
        reset_wallet(db, starting_balance=0)
    with pytest.raises(ValueError, match="starting_balance"):
        reset_wallet(db, starting_balance=-10.0)


def test_post_reset_polilydb_reopen_has_clean_wallet(tmp_path):
    """After reset, a fresh PolilyDB instance must see the re-seeded wallet."""
    db = PolilyDB(tmp_path / "t.db")
    reset_wallet(db, starting_balance=77.0)
    db.close()
    db2 = PolilyDB(tmp_path / "t.db")
    # Wallet stays at 77 (not overwritten by auto-migration's default 100).
    row = db2.conn.execute("SELECT * FROM wallet WHERE id=1").fetchone()
    assert row["cash_usd"] == 77.0
    assert row["starting_balance"] == 77.0


# --- CLI integration -----------------------------------------------------


def test_cli_reset_wallet_only_end_to_end(tmp_path, monkeypatch):
    """`polily reset --wallet-only -y` wipes wallet-side state but keeps events."""
    from unittest.mock import MagicMock

    from typer.testing import CliRunner

    from polily import cli

    # Seed a DB at a known path + inject some state to be wiped. We seed a
    # position directly (not via paper_trades migration) so that the second
    # PolilyDB() opened inside the CLI doesn't re-run aggregation and conflict
    # with the existing position row.
    db_path = tmp_path / "polily.db"
    db = PolilyDB(db_path)
    _seed_event_and_market(db)
    db.conn.execute(
        """INSERT INTO positions
           (market_id,side,event_id,shares,avg_cost,cost_basis,title,opened_at,updated_at)
           VALUES ('m1','yes','e1',10,0.5,5,'Q','t','t')""",
    )
    db.conn.commit()
    db.close()

    # Stub config loader so the CLI targets our tmp DB + a known balance.
    fake_cfg = MagicMock()
    fake_cfg.wallet.starting_balance = 123.0
    fake_cfg.archiving.db_file = str(db_path)
    monkeypatch.setattr(cli, "_load_user_config", lambda: fake_cfg)
    # No daemon in tests.
    monkeypatch.setattr(cli, "_stop_daemon_if_running", lambda: None)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["reset", "--wallet-only", "-y"])
    assert result.exit_code == 0, result.output
    assert "Wallet reset to $123.0" in result.output

    # Verify the wipe + re-seed actually happened in the DB.
    db2 = PolilyDB(db_path)
    assert db2.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
    assert db2.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    row = db2.conn.execute("SELECT cash_usd FROM wallet WHERE id=1").fetchone()
    assert row["cash_usd"] == 123.0


def test_cli_reset_wallet_only_stops_daemon(tmp_path, monkeypatch):
    """`reset --wallet-only` must stop the scheduler daemon before wiping — the
    shared DB conn is otherwise racy against the poll/AI threads."""
    from unittest.mock import MagicMock

    from typer.testing import CliRunner

    from polily import cli

    db_path = tmp_path / "polily.db"
    PolilyDB(db_path).close()  # init schema + wallet singleton

    fake_cfg = MagicMock()
    fake_cfg.wallet.starting_balance = 100.0
    fake_cfg.archiving.db_file = str(db_path)
    monkeypatch.setattr(cli, "_load_user_config", lambda: fake_cfg)

    stop_spy = MagicMock()
    monkeypatch.setattr(cli, "_stop_daemon_if_running", stop_spy)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["reset", "--wallet-only", "-y"])
    assert result.exit_code == 0, result.output
    stop_spy.assert_called_once()


def test_cli_reset_wallet_only_cancelled_does_nothing(tmp_path, monkeypatch):
    """User answering 'n' to the confirm prompt must leave the DB untouched."""
    from unittest.mock import MagicMock

    from typer.testing import CliRunner

    from polily import cli

    db_path = tmp_path / "polily.db"
    db = PolilyDB(db_path)
    _seed_event_and_market(db)
    db.conn.execute(
        """INSERT INTO positions
           (market_id,side,event_id,shares,avg_cost,cost_basis,title,opened_at,updated_at)
           VALUES ('m1','yes','e1',10,0.5,5,'Q','t','t')""",
    )
    db.conn.commit()
    db.close()

    fake_cfg = MagicMock()
    fake_cfg.wallet.starting_balance = 100.0
    fake_cfg.archiving.db_file = str(db_path)
    monkeypatch.setattr(cli, "_load_user_config", lambda: fake_cfg)
    stop_spy = MagicMock()
    monkeypatch.setattr(cli, "_stop_daemon_if_running", stop_spy)

    runner = CliRunner()
    # Answer 'n' to the confirm prompt (no -y flag given).
    result = runner.invoke(cli.app, ["reset", "--wallet-only"], input="n\n")
    assert result.exit_code == 0
    assert "Cancelled" in result.output
    # Daemon must NOT be stopped if user cancelled.
    stop_spy.assert_not_called()
    # Positions still there.
    db2 = PolilyDB(db_path)
    assert db2.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 1
