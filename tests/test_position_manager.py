"""Tests for PositionManager — aggregated (market_id, side) positions."""

import pytest

from scanner.core.db import PolilyDB
from scanner.core.positions import (
    InsufficientShares,
    PositionManager,
    PositionNotFound,
)


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    # seed events + markets (to satisfy FK)
    db.conn.execute(
        "INSERT INTO events (event_id,title,updated_at) VALUES ('e1','Test Event','t')"
    )
    db.conn.execute(
        "INSERT INTO markets (market_id,event_id,question,updated_at) VALUES ('m1','e1','Q','t')"
    )
    db.conn.commit()
    return db


@pytest.fixture
def pm(db):
    return PositionManager(db)


def test_add_shares_creates_new_position(pm):
    pm.add_shares(
        market_id="m1",
        side="yes",
        event_id="e1",
        title="Q",
        shares=10.0,
        price=0.5,
    )
    p = pm.get_position("m1", "yes")
    assert p["shares"] == 10.0
    assert p["avg_cost"] == 0.5
    assert p["cost_basis"] == 5.0
    assert p["realized_pnl"] == 0.0


def test_add_shares_weighted_average(pm):
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10.0, price=0.5
    )
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10.0, price=0.7
    )
    p = pm.get_position("m1", "yes")
    assert p["shares"] == 20.0
    assert p["avg_cost"] == pytest.approx(0.6, abs=0.001)
    assert p["cost_basis"] == pytest.approx(12.0, abs=0.001)


def test_yes_and_no_coexist(pm):
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10.0, price=0.5
    )
    pm.add_shares(
        market_id="m1", side="no", event_id="e1", title="Q", shares=5.0, price=0.45
    )
    assert pm.get_position("m1", "yes")["shares"] == 10.0
    assert pm.get_position("m1", "no")["shares"] == 5.0


def test_remove_shares_partial_keeps_avg_cost(pm):
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10.0, price=0.5
    )
    realized = pm.remove_shares(market_id="m1", side="yes", shares=4.0, price=0.7)
    assert realized == pytest.approx(0.8)  # (0.7 - 0.5) * 4
    p = pm.get_position("m1", "yes")
    assert p["shares"] == 6.0
    assert p["avg_cost"] == 0.5  # unchanged
    assert p["realized_pnl"] == pytest.approx(0.8)


def test_remove_shares_full_deletes_position(pm):
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10.0, price=0.5
    )
    pm.remove_shares(market_id="m1", side="yes", shares=10.0, price=0.6)
    assert pm.get_position("m1", "yes") is None


def test_remove_exceeding_shares_raises(pm):
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=5.0, price=0.5
    )
    with pytest.raises(InsufficientShares):
        pm.remove_shares(market_id="m1", side="yes", shares=10.0, price=0.6)


def test_remove_from_nonexistent_raises(pm):
    with pytest.raises(PositionNotFound):
        pm.remove_shares(market_id="m1", side="yes", shares=1.0, price=0.5)


def test_get_all_and_get_event_positions(pm, db):
    db.conn.execute(
        "INSERT INTO events (event_id,title,updated_at) VALUES ('e2','E2','t')"
    )
    db.conn.execute(
        "INSERT INTO markets (market_id,event_id,question,updated_at) VALUES ('m2','e2','Q2','t')"
    )
    db.conn.commit()
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10.0, price=0.5
    )
    pm.add_shares(
        market_id="m2", side="yes", event_id="e2", title="Q2", shares=5.0, price=0.3
    )
    assert len(pm.get_all_positions()) == 2
    assert len(pm.get_event_positions("e1")) == 1


# --- Input validation: boundaries -----------------------------------------


def test_add_shares_rejects_non_positive_shares(pm):
    with pytest.raises(ValueError, match="shares"):
        pm.add_shares(
            market_id="m1", side="yes", event_id="e1", title="Q", shares=0, price=0.5
        )
    with pytest.raises(ValueError, match="shares"):
        pm.add_shares(
            market_id="m1",
            side="yes",
            event_id="e1",
            title="Q",
            shares=-1.0,
            price=0.5,
        )


def test_add_shares_rejects_invalid_price(pm):
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="price"):
            pm.add_shares(
                market_id="m1",
                side="yes",
                event_id="e1",
                title="Q",
                shares=10.0,
                price=bad,
            )


def test_add_shares_rejects_invalid_side(pm):
    with pytest.raises(ValueError, match="side"):
        pm.add_shares(
            market_id="m1",
            side="maybe",
            event_id="e1",
            title="Q",
            shares=10.0,
            price=0.5,
        )


def test_remove_shares_rejects_non_positive(pm):
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=5.0, price=0.5
    )
    with pytest.raises(ValueError, match="shares"):
        pm.remove_shares(market_id="m1", side="yes", shares=0, price=0.5)


# --- Atomicity contract (required by Task 1.6 TradeEngine) ---------------


def test_add_shares_respects_commit_false(db):
    pm = PositionManager(db)
    pm.add_shares(
        market_id="m1",
        side="yes",
        event_id="e1",
        title="Q",
        shares=10.0,
        price=0.5,
        commit=False,
    )
    # Same connection sees the pending row.
    assert pm.get_position("m1", "yes") is not None
    # Rolling back reverts.
    db.conn.rollback()
    assert pm.get_position("m1", "yes") is None


def test_remove_shares_respects_commit_false(db):
    pm = PositionManager(db)
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10.0, price=0.5
    )
    # Now the position is committed; rollback on remove must restore it fully.
    pm.remove_shares(market_id="m1", side="yes", shares=5.0, price=0.7, commit=False)
    assert pm.get_position("m1", "yes")["shares"] == 5.0
    db.conn.rollback()
    p = pm.get_position("m1", "yes")
    assert p["shares"] == 10.0
    assert p["realized_pnl"] == 0.0


def test_add_then_remove_atomic_happy_path(db):
    """Multi-op commit=False flow: buy + partial sell, single commit, durable."""
    pm = PositionManager(db)
    pm.add_shares(
        market_id="m1",
        side="yes",
        event_id="e1",
        title="Q",
        shares=10.0,
        price=0.5,
        commit=False,
    )
    pm.remove_shares(market_id="m1", side="yes", shares=3.0, price=0.6, commit=False)
    db.conn.commit()
    # Durable across fresh connection.
    db2 = PolilyDB(db.db_path)
    row = db2.conn.execute(
        "SELECT * FROM positions WHERE market_id='m1' AND side='yes'"
    ).fetchone()
    assert row["shares"] == pytest.approx(7.0)
    assert row["realized_pnl"] == pytest.approx(0.3)  # (0.6-0.5)*3


def test_remove_partial_cost_basis_tracks_remaining(pm):
    """cost_basis after partial close should equal remaining shares * avg_cost."""
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10.0, price=0.5
    )
    pm.remove_shares(market_id="m1", side="yes", shares=4.0, price=0.7)
    p = pm.get_position("m1", "yes")
    assert p["cost_basis"] == pytest.approx(6 * 0.5)


def test_full_close_rollback_restores_position(db):
    """commit=False remove that fully closes the row must be fully revertible."""
    pm = PositionManager(db)
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10.0, price=0.5
    )
    pm.remove_shares(
        market_id="m1", side="yes", shares=10.0, price=0.9, commit=False
    )
    # Position deleted in current txn.
    assert pm.get_position("m1", "yes") is None
    db.conn.rollback()
    # Rollback brings the whole row back — shares AND realized_pnl.
    p = pm.get_position("m1", "yes")
    assert p is not None
    assert p["shares"] == 10.0
    assert p["realized_pnl"] == 0.0


def test_epsilon_boundary_triggers_delete(pm):
    """Residual shares below _SHARES_EPS (1e-9) should trigger DELETE, not UPDATE."""
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10.0, price=0.5
    )
    pm.remove_shares(
        market_id="m1", side="yes", shares=10.0 - 5e-10, price=0.6
    )
    assert pm.get_position("m1", "yes") is None
