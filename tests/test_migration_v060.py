"""Tests for v0.5.x → v0.6.0 one-time migration."""

import pytest

from scanner.core.db import PolilyDB
from scanner.core.migration_v060 import migrate_if_needed


def _seed_event_and_market(db: PolilyDB, event_id: str = "e1", market_id: str = "m1"):
    db.conn.execute(
        "INSERT OR IGNORE INTO events (event_id,title,updated_at) VALUES (?,?,?)",
        (event_id, "Test Event", "t"),
    )
    db.conn.execute(
        "INSERT OR IGNORE INTO markets (market_id,event_id,question,updated_at) VALUES (?,?,?,?)",
        (market_id, event_id, "Q", "t"),
    )
    db.conn.commit()


# --- wallet singleton -----------------------------------------------------


def test_fresh_db_creates_wallet(tmp_path):
    """Fresh DB: migration ensures wallet singleton at starting_balance."""
    db = PolilyDB(tmp_path / "t.db")
    migrate_if_needed(db, starting_balance=100.0)
    row = db.conn.execute("SELECT * FROM wallet WHERE id=1").fetchone()
    assert row is not None
    assert row["cash_usd"] == 100.0


def test_fresh_db_honors_starting_balance(tmp_path):
    """starting_balance override flows through when wallet created fresh."""
    db = PolilyDB(tmp_path / "t.db")
    # Wipe wallet that auto-migration may have created with default balance.
    db.conn.execute("DELETE FROM wallet")
    db.conn.commit()
    migrate_if_needed(db, starting_balance=250.0)
    row = db.conn.execute("SELECT * FROM wallet WHERE id=1").fetchone()
    assert row["cash_usd"] == 250.0


def test_migration_is_idempotent(tmp_path):
    """Second call must not duplicate wallet or reset cash to starting_balance."""
    db = PolilyDB(tmp_path / "t.db")
    migrate_if_needed(db, starting_balance=100.0)
    db.conn.execute("UPDATE wallet SET cash_usd=50 WHERE id=1")
    db.conn.commit()
    migrate_if_needed(db, starting_balance=100.0)
    row = db.conn.execute("SELECT * FROM wallet WHERE id=1").fetchone()
    assert row["cash_usd"] == 50.0  # unchanged


# --- paper_trades aggregation --------------------------------------------


def test_aggregates_open_paper_trades_into_positions(tmp_path):
    """Two open BUY_YES on same market at different prices → single aggregated position."""
    db = PolilyDB(tmp_path / "t.db")
    _seed_event_and_market(db)
    db.conn.executescript("""
        INSERT INTO paper_trades
          (id,event_id,market_id,title,side,entry_price,position_size_usd,status,marked_at)
          VALUES ('t1','e1','m1','Q','yes',0.5,10,'open','2026-01-01');
        INSERT INTO paper_trades
          (id,event_id,market_id,title,side,entry_price,position_size_usd,status,marked_at)
          VALUES ('t2','e1','m1','Q','yes',0.7,14,'open','2026-01-02');
    """)
    db.conn.commit()
    migrate_if_needed(db, starting_balance=100.0)
    pos = db.conn.execute(
        "SELECT * FROM positions WHERE market_id='m1' AND side='yes'"
    ).fetchone()
    # t1: shares = 10/0.5 = 20, t2: shares = 14/0.7 = 20, total = 40
    # avg_cost = (10+14)/40 = 0.6
    assert pos["shares"] == pytest.approx(40.0)
    assert pos["avg_cost"] == pytest.approx(0.6)
    assert pos["cost_basis"] == pytest.approx(24.0)
    assert pos["realized_pnl"] == 0.0


def test_yes_and_no_paper_trades_aggregate_separately(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    _seed_event_and_market(db)
    db.conn.executescript("""
        INSERT INTO paper_trades
          (id,event_id,market_id,title,side,entry_price,position_size_usd,status,marked_at)
          VALUES ('t1','e1','m1','Q','yes',0.5,10,'open','2026-01-01');
        INSERT INTO paper_trades
          (id,event_id,market_id,title,side,entry_price,position_size_usd,status,marked_at)
          VALUES ('t2','e1','m1','Q','no',0.4,8,'open','2026-01-01');
    """)
    db.conn.commit()
    migrate_if_needed(db, starting_balance=100.0)
    assert db.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 2


def test_resolved_paper_trades_not_migrated(tmp_path):
    """Resolved legacy trades stay as read-only history — no position created."""
    db = PolilyDB(tmp_path / "t.db")
    _seed_event_and_market(db)
    db.conn.execute(
        """INSERT INTO paper_trades
           (id,event_id,market_id,title,side,entry_price,position_size_usd,status,
            marked_at,resolved_at,resolved_result)
           VALUES ('t1','e1','m1','Q','yes',0.5,10,'resolved',
                   '2026-01-01','2026-01-02','yes')""",
    )
    db.conn.commit()
    migrate_if_needed(db, starting_balance=100.0)
    assert db.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0


def test_zero_entry_price_trade_ignored(tmp_path):
    """Corrupt row with entry_price=0 must be skipped (division by zero guard)."""
    db = PolilyDB(tmp_path / "t.db")
    _seed_event_and_market(db)
    db.conn.execute(
        """INSERT INTO paper_trades
           (id,event_id,market_id,title,side,entry_price,position_size_usd,status,marked_at)
           VALUES ('t1','e1','m1','Q','yes',0,10,'open','2026-01-01')""",
    )
    db.conn.commit()
    # Must not raise; must not insert a bogus position.
    migrate_if_needed(db, starting_balance=100.0)
    assert db.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0


# --- MIGRATION bookmark ---------------------------------------------------


def test_bookmark_inserted_when_legacy_data_exists(tmp_path):
    """Real v0.5.x → v0.6.0 upgrade: paper_trades has rows → bookmark inserted."""
    db = PolilyDB(tmp_path / "t.db")
    _seed_event_and_market(db)
    db.conn.execute(
        """INSERT INTO paper_trades
           (id,event_id,market_id,title,side,entry_price,position_size_usd,status,marked_at)
           VALUES ('t1','e1','m1','Q','yes',0.5,10,'open','2026-01-01')""",
    )
    db.conn.commit()
    migrate_if_needed(db, starting_balance=100.0)
    tx = db.conn.execute(
        "SELECT * FROM wallet_transactions WHERE type='MIGRATION'"
    ).fetchone()
    assert tx is not None
    assert "v0.6.0" in tx["notes"]
    assert "1 open positions" in tx["notes"]


def test_fresh_install_skips_bookmark(tmp_path):
    """Fresh install (no paper_trades) must not leave a spurious MIGRATION row.

    Reason: the wallet tests assert list_transactions() == [] on fresh fixtures.
    Bookmarking fresh installs would poison every unrelated test suite.
    """
    db = PolilyDB(tmp_path / "t.db")
    migrate_if_needed(db, starting_balance=100.0)
    bookmark = db.conn.execute(
        "SELECT 1 FROM wallet_transactions WHERE type='MIGRATION'"
    ).fetchone()
    assert bookmark is None


def test_bookmark_prevents_second_aggregation(tmp_path):
    """After migration ran, a second call must NOT re-aggregate even if new
    paper_trades appear (shouldn't happen post-v0.6.0, but bookmark is the guard)."""
    db = PolilyDB(tmp_path / "t.db")
    _seed_event_and_market(db)
    db.conn.execute(
        """INSERT INTO paper_trades
           (id,event_id,market_id,title,side,entry_price,position_size_usd,status,marked_at)
           VALUES ('t1','e1','m1','Q','yes',0.5,10,'open','2026-01-01')""",
    )
    db.conn.commit()
    migrate_if_needed(db, starting_balance=100.0)
    assert db.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 1

    # Add another legacy-style trade (adversarial) and call again.
    db.conn.execute(
        """INSERT INTO paper_trades
           (id,event_id,market_id,title,side,entry_price,position_size_usd,status,marked_at)
           VALUES ('t2','e1','m1','Q','no',0.4,8,'open','2026-01-03')""",
    )
    db.conn.commit()
    migrate_if_needed(db, starting_balance=100.0)
    # Still 1 position — bookmark blocked re-aggregation.
    assert db.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 1


# --- auto-migration via PolilyDB.__init__ --------------------------------


def test_polilydb_auto_creates_wallet_on_init(tmp_path):
    """Newly instantiated PolilyDB auto-runs migration and seeds the wallet."""
    db = PolilyDB(tmp_path / "t.db")
    row = db.conn.execute("SELECT * FROM wallet WHERE id=1").fetchone()
    assert row is not None
    assert row["cash_usd"] == 100.0  # default from ScannerConfig


def test_polilydb_reopen_does_not_reset_cash(tmp_path):
    """Re-opening an existing DB via PolilyDB() must preserve wallet state."""
    db = PolilyDB(tmp_path / "t.db")
    db.conn.execute("UPDATE wallet SET cash_usd=42 WHERE id=1")
    db.conn.commit()
    db.close()
    db2 = PolilyDB(tmp_path / "t.db")
    row = db2.conn.execute("SELECT * FROM wallet WHERE id=1").fetchone()
    assert row["cash_usd"] == 42.0
