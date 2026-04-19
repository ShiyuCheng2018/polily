"""Tests for ResolutionHandler — auto settlement after market resolution."""

import pytest

from scanner.core.db import PolilyDB
from scanner.core.positions import PositionManager
from scanner.core.wallet import WalletService
from scanner.daemon.resolution import ResolutionHandler, derive_winner


def _setup(tmp_path, position_shares: float = 20.0, entry_price: float = 0.5):
    """Seed event + market + one YES position at known cost basis."""
    db = PolilyDB(tmp_path / "t.db")
    db.conn.executescript("""
        INSERT INTO events (event_id,title,updated_at) VALUES ('e1','E','t');
        INSERT INTO markets (market_id,event_id,question,closed,updated_at)
            VALUES ('m1','e1','Q',1,'t');
    """)
    db.conn.commit()
    wallet = WalletService(db)
    pm = PositionManager(db)
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q",
        shares=position_shares, price=entry_price,
    )
    rh = ResolutionHandler(db, wallet, pm)
    return db, wallet, pm, rh


# --- derive_winner ------------------------------------------------------


@pytest.mark.parametrize(
    "outcome_prices,expected",
    [
        # Clean resolved-winning-side pairs (>= 0.99 threshold).
        (["1", "0"], "yes"),
        (["0", "1"], "no"),
        (["1.0", "0.0"], "yes"),
        (["0.00", "1.00"], "no"),
        # Near-winning (pre-settlement oracle proposal, still above 0.99).
        (["0.995", "0.005"], "yes"),
        (["0.005", "0.995"], "no"),
        # Unresolved / in-progress / disputed.
        (["0", "0"], None),
        (["0.6", "0.3"], None),
        (["0.98", "0.02"], None),  # just below threshold
        # UMA DVM split — extremely rare.
        (["0.5", "0.5"], "split"),
        (["0.500", "0.500"], "split"),
    ],
)
def test_derive_winner(outcome_prices, expected):
    assert derive_winner(outcome_prices) == expected


def test_derive_winner_malformed_input_returns_none():
    assert derive_winner([]) is None
    assert derive_winner(["1"]) is None  # wrong length
    assert derive_winner(["not-a-number", "0"]) is None
    assert derive_winner(["1", "0", "0"]) is None  # too many


# --- derive_winner UMA resolution gate ----------------------------------
#
# Gamma returns `umaResolutionStatuses` as a history array. During the
# 2+ hour UMA challenge window (last status == "proposed"), `outcomePrices`
# reflects the proposer's guess — which can flip if disputed. Settling here
# would write phantom RESOLVE rows to wallet_transactions.
#
# Gate:
#   uma=[]                 → non-UMA market (price feed) → settle by price
#   uma[-1]=="resolved"    → UMA final → settle by price
#   uma[-1] in {"proposed","disputed", ...} → defer (next poll tick)


@pytest.mark.parametrize(
    "uma_statuses,outcome_prices,expected",
    [
        # Non-UMA markets (price feed authoritative; e.g. Crypto Up/Down).
        ([], ["1", "0"], "yes"),
        ([], ["0", "1"], "no"),
        # UMA final state — last entry "resolved".
        (["proposed", "resolved"], ["1", "0"], "yes"),
        (["proposed", "resolved"], ["0", "1"], "no"),
        (["proposed", "disputed", "resolved"], ["0", "1"], "no"),
        # UMA still in challenge window — outcomePrices set but can flip.
        (["proposed"], ["1", "0"], None),
        (["proposed"], ["0", "1"], None),
        # UMA dispute in progress.
        (["disputed"], ["1", "0"], None),
        (["proposed", "disputed"], ["1", "0"], None),
        # Unknown terminal status — conservative defer.
        (["unknown"], ["1", "0"], None),
    ],
)
def test_derive_winner_gated_on_uma_status(uma_statuses, outcome_prices, expected):
    assert (
        derive_winner(outcome_prices, uma_statuses=uma_statuses) == expected
    )


def test_derive_winner_backward_compatible_without_uma_argument():
    """Legacy single-arg callers keep working (price-only path).

    The POC showed many markets have `umaResolutionStatuses=[]` — non-UMA
    markets where the price feed is authoritative. Omitting the kwarg has
    the same semantics so a caller that forgets it stays safe for the
    non-UMA half of the universe; UMA markets will still get blocked
    because the caller must provide the list to unlock them (see the
    poll_job integration tests).
    """
    assert derive_winner(["1", "0"]) == "yes"
    assert derive_winner(["0", "1"]) == "no"
    assert derive_winner(["0.5", "0.5"]) == "split"


# --- resolve_market return value (operator-log support) ---------------


def test_resolve_market_returns_settled_count_and_credit(tmp_path):
    """Caller (poll_job) needs these values to emit a poll.log audit line."""
    db, wallet, pm, rh = _setup(tmp_path)
    n, credited = rh.resolve_market("m1", "yes")
    assert n == 1
    assert credited == pytest.approx(20.0)  # 20 shares × $1 payout


def test_resolve_market_returns_zero_when_no_positions(tmp_path):
    """Idempotent second-call returns (0, 0.0) — lets caller suppress log noise."""
    db, wallet, pm, rh = _setup(tmp_path)
    rh.resolve_market("m1", "yes")  # settles
    n, credited = rh.resolve_market("m1", "yes")  # second call — nothing left
    assert n == 0
    assert credited == 0.0


def test_resolve_market_returns_split_credit(tmp_path):
    db, wallet, pm, rh = _setup(tmp_path)
    n, credited = rh.resolve_market("m1", "split")
    assert n == 1
    assert credited == pytest.approx(10.0)  # 20 shares × $0.5


# --- resolve_market: happy / loss / split / idempotent ------------------


def test_resolve_yes_wins_credits_cash(tmp_path):
    db, wallet, pm, rh = _setup(tmp_path)
    cash_before = wallet.get_cash()
    rh.resolve_market("m1", "yes")
    # 20 shares × $1 = $20 credited; the bought-at-0.5 cost ($10) was
    # already deducted when the position opened, so delta = +20.
    assert wallet.get_cash() == pytest.approx(cash_before + 20.0)
    assert pm.get_position("m1", "yes") is None


def test_resolve_no_wins_yes_position_loses_all(tmp_path):
    """YES holder loses the full cost basis when NO wins."""
    db, wallet, pm, rh = _setup(tmp_path)
    cash_before = wallet.get_cash()
    rh.resolve_market("m1", "no")
    # Shares worth 0 → proceeds 0; the original $10 cost is lost.
    assert wallet.get_cash() == cash_before
    tx = db.conn.execute(
        "SELECT * FROM wallet_transactions WHERE type='RESOLVE'"
    ).fetchone()
    assert tx["amount_usd"] == 0.0
    assert tx["realized_pnl"] == pytest.approx(-10.0)  # 0 - cost_basis(10)
    assert tx["notes"] == "NO won"
    assert pm.get_position("m1", "yes") is None


def test_resolve_split_half_refund(tmp_path):
    db, wallet, pm, rh = _setup(tmp_path)
    cash_before = wallet.get_cash()
    rh.resolve_market("m1", "split")
    # 20 shares × $0.5 = $10 refund (break-even vs cost basis of $10).
    assert wallet.get_cash() == pytest.approx(cash_before + 10.0)
    tx = db.conn.execute(
        "SELECT * FROM wallet_transactions WHERE type='RESOLVE'"
    ).fetchone()
    assert tx["amount_usd"] == pytest.approx(10.0)
    assert tx["realized_pnl"] == pytest.approx(0.0)
    assert "split" in tx["notes"].lower()


def test_resolve_idempotent_after_position_deleted(tmp_path):
    """Second call on a resolved market is a no-op (no positions left)."""
    db, wallet, pm, rh = _setup(tmp_path)
    rh.resolve_market("m1", "yes")
    cash_after_first = wallet.get_cash()
    tx_count_after_first = len(wallet.list_transactions())
    rh.resolve_market("m1", "yes")  # second call
    assert wallet.get_cash() == cash_after_first
    assert len(wallet.list_transactions()) == tx_count_after_first


def test_resolve_persists_markets_resolved_outcome(tmp_path):
    """After resolution, markets.resolved_outcome is the authoritative record."""
    db, wallet, pm, rh = _setup(tmp_path)
    rh.resolve_market("m1", "yes")
    outcome = db.conn.execute(
        "SELECT resolved_outcome FROM markets WHERE market_id='m1'"
    ).fetchone()["resolved_outcome"]
    assert outcome == "yes"


def test_resolve_persists_outcome_even_when_no_positions(tmp_path):
    """A market that resolved while user held nothing still gets the DB record."""
    db = PolilyDB(tmp_path / "t.db")
    db.conn.executescript("""
        INSERT INTO events (event_id,title,updated_at) VALUES ('e1','E','t');
        INSERT INTO markets (market_id,event_id,question,closed,updated_at)
            VALUES ('m1','e1','Q',1,'t');
    """)
    db.conn.commit()
    wallet = WalletService(db)
    pm = PositionManager(db)
    rh = ResolutionHandler(db, wallet, pm)
    rh.resolve_market("m1", "no")
    outcome = db.conn.execute(
        "SELECT resolved_outcome FROM markets WHERE market_id='m1'"
    ).fetchone()["resolved_outcome"]
    assert outcome == "no"
    # No transactions written since no positions to settle.
    assert wallet.list_transactions() == []


def test_resolve_handles_both_sides_held(tmp_path):
    """If user held both YES and NO on the same market, both positions settle."""
    db = PolilyDB(tmp_path / "t.db")
    db.conn.executescript("""
        INSERT INTO events (event_id,title,updated_at) VALUES ('e1','E','t');
        INSERT INTO markets (market_id,event_id,question,closed,updated_at)
            VALUES ('m1','e1','Q',1,'t');
    """)
    db.conn.commit()
    wallet = WalletService(db)
    pm = PositionManager(db)
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10, price=0.5
    )
    pm.add_shares(
        market_id="m1", side="no", event_id="e1", title="Q", shares=5, price=0.4
    )
    cash_before = wallet.get_cash()
    rh = ResolutionHandler(db, wallet, pm)
    rh.resolve_market("m1", "yes")
    # YES: 10 shares → $10 credited. NO: 5 shares → $0.
    assert wallet.get_cash() == pytest.approx(cash_before + 10.0)
    assert pm.get_position("m1", "yes") is None
    assert pm.get_position("m1", "no") is None
    resolves = wallet.list_transactions(tx_type="RESOLVE")
    assert len(resolves) == 2


def test_resolve_rejects_invalid_winner(tmp_path):
    db, wallet, pm, rh = _setup(tmp_path)
    with pytest.raises(ValueError, match="winner_side"):
        rh.resolve_market("m1", "maybe")


# --- Atomicity: partial-failure rollback --------------------------------


def test_resolve_midflight_failure_rolls_back_all(tmp_path):
    """If wallet.credit raises on the 2nd position, the 1st credit AND the
    markets.resolved_outcome update must also roll back — no double-credit
    on retry."""
    from unittest.mock import patch

    db = PolilyDB(tmp_path / "t.db")
    db.conn.executescript("""
        INSERT INTO events (event_id,title,updated_at) VALUES ('e1','E','t');
        INSERT INTO markets (market_id,event_id,question,closed,updated_at)
            VALUES ('m1','e1','Q',1,'t');
    """)
    db.conn.commit()
    wallet = WalletService(db)
    pm = PositionManager(db)
    pm.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10, price=0.5
    )
    pm.add_shares(
        market_id="m1", side="no", event_id="e1", title="Q", shares=5, price=0.4
    )
    cash_before = wallet.get_cash()
    rh = ResolutionHandler(db, wallet, pm)

    # First credit call succeeds; second raises.
    original = wallet.credit
    call_count = [0]

    def flaky_credit(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 2:
            raise RuntimeError("simulated mid-resolution failure")
        return original(*args, **kwargs)

    with patch.object(wallet, "credit", side_effect=flaky_credit), pytest.raises(
        RuntimeError
    ):
        rh.resolve_market("m1", "yes")

    # Cash unchanged: the first credit was rolled back.
    assert wallet.get_cash() == cash_before
    # Both positions survive — retry has clean slate.
    assert pm.get_position("m1", "yes") is not None
    assert pm.get_position("m1", "no") is not None
    # markets.resolved_outcome also rolled back (stays NULL).
    outcome = db.conn.execute(
        "SELECT resolved_outcome FROM markets WHERE market_id='m1'"
    ).fetchone()["resolved_outcome"]
    assert outcome is None
    # No orphan RESOLVE ledger rows.
    assert wallet.list_transactions(tx_type="RESOLVE") == []


def test_resolve_unknown_market_logs_warning(tmp_path, caplog):
    """UPDATE rows-affected=0 should log a warning but not raise."""
    import logging as _logging

    db = PolilyDB(tmp_path / "t.db")
    wallet = WalletService(db)
    pm = PositionManager(db)
    rh = ResolutionHandler(db, wallet, pm)
    with caplog.at_level(_logging.WARNING, logger="scanner.daemon.resolution"):
        rh.resolve_market("nonexistent", "yes")
    assert any("nonexistent" in rec.message for rec in caplog.records)
