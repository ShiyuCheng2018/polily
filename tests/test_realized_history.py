"""PolilyService.get_realized_history / get_realized_summary.

Feeds the (rewritten) HistoryView in v0.6.0+ — sourced from
`wallet_transactions` SELL + RESOLVE rows, not the legacy `paper_trades`
table. Rationale in docs: every realized-P&L event (active sell or
oracle settlement) is one ledger row; history view shows them in
reverse chronological order.

FEE rows are tracked separately in the ledger but belong logically to
their parent SELL/BUY — these tests assert the service pairs them by
(market_id, side, close-in-time created_at) so the history view can
show the true per-event fee without a second query.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scanner.core.config import ScannerConfig
from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.tui.service import PolilyService


def _svc(tmp_path) -> PolilyService:
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="e1", title="Event 1", updated_at="now"), db)
    upsert_market(
        MarketRow(
            market_id="m1", event_id="e1", question="Will X win?",
            clob_token_id_yes="ty", clob_token_id_no="tn",
            yes_price=0.5, no_price=0.5, updated_at="now",
            fees_enabled=1, fee_rate=0.072,  # crypto_fees_v2 style — forces FEE rows
        ),
        db,
    )
    # v0.8.0: PolilyService.execute_buy/sell require auto_monitor=1.
    from scanner.core.monitor_store import upsert_event_monitor
    upsert_event_monitor("e1", auto_monitor=True, db=db)
    return PolilyService(config=ScannerConfig(), db=db)


# ---- get_realized_history --------------------------------------------


def test_realized_history_empty_when_no_activity(tmp_path):
    svc = _svc(tmp_path)
    assert svc.get_realized_history() == []


def test_realized_history_excludes_pure_buys(tmp_path):
    """A BUY alone doesn't realize P&L — must NOT show up in history."""
    svc = _svc(tmp_path)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)

    assert svc.get_realized_history() == []


def test_realized_history_returns_sell_row_with_fields(tmp_path):
    """Buy then full sell → history has 1 row with realized_pnl + fee."""
    svc = _svc(tmp_path)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.6,
    ):
        svc.execute_sell(market_id="m1", side="yes", shares=10.0)

    hist = svc.get_realized_history()
    assert len(hist) == 1
    row = hist[0]
    assert row["type"] == "SELL"
    assert row["market_id"] == "m1"
    assert row["side"] == "yes"
    assert row["shares"] == pytest.approx(10.0)
    assert row["price"] == pytest.approx(0.6)
    assert row["realized_pnl"] == pytest.approx(1.0)  # (0.6 - 0.5) * 10
    assert row["fee_usd"] > 0  # fees_enabled=1 produces a FEE row
    # Title must be pulled from markets table for display.
    assert row["title"] == "Will X win?"
    assert "created_at" in row


def test_realized_history_orders_by_created_at_desc(tmp_path):
    """Multiple realize events → newest first."""
    svc = _svc(tmp_path)
    # First round-trip — oldest.
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.6,
    ):
        svc.execute_sell(market_id="m1", side="yes", shares=5.0)
    # Second partial sell — newest.
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.7,
    ):
        svc.execute_sell(market_id="m1", side="yes", shares=5.0)

    hist = svc.get_realized_history()
    assert len(hist) == 2
    # Desc by time: latest (0.7) first, older (0.6) second.
    assert hist[0]["price"] == pytest.approx(0.7)
    assert hist[1]["price"] == pytest.approx(0.6)


def test_realized_history_includes_resolve_rows(tmp_path):
    """RESOLVE rows (from oracle settlement) must appear alongside SELL."""
    from scanner.daemon.resolution import ResolutionHandler

    svc = _svc(tmp_path)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    # Mark market closed so ResolutionHandler proceeds
    svc.db.conn.execute("UPDATE markets SET closed=1 WHERE market_id='m1'")
    svc.db.conn.commit()
    resolver = ResolutionHandler(svc.db, svc.wallet, svc.positions)
    resolver.resolve_market("m1", "yes")

    hist = svc.get_realized_history()
    assert len(hist) == 1
    row = hist[0]
    assert row["type"] == "RESOLVE"
    assert row["side"] == "yes"
    assert row["shares"] == pytest.approx(10.0)
    assert row["price"] == pytest.approx(1.0)  # YES won → $1 per share
    assert row["realized_pnl"] == pytest.approx(5.0)  # (1.0 - 0.5) * 10
    assert row["fee_usd"] == 0.0  # RESOLVE doesn't charge fees
    assert row["title"] == "Will X win?"


# ---- get_realized_summary --------------------------------------------


def test_realized_summary_empty_state(tmp_path):
    svc = _svc(tmp_path)
    s = svc.get_realized_summary()
    assert s == {"count": 0, "total_pnl": 0.0, "total_fees": 0.0}


def test_realized_summary_aggregates_sell_and_resolve(tmp_path):
    """Summary: count of realize events, sum of realized_pnl, sum of FEE rows
    (FEE is a separate row type but belongs to this scope conceptually)."""
    from scanner.daemon.resolution import ResolutionHandler

    svc = _svc(tmp_path)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.6,
    ):
        svc.execute_sell(market_id="m1", side="yes", shares=5.0)

    # Close out remaining 5 by resolution.
    svc.db.conn.execute("UPDATE markets SET closed=1 WHERE market_id='m1'")
    svc.db.conn.commit()
    ResolutionHandler(svc.db, svc.wallet, svc.positions).resolve_market("m1", "yes")

    s = svc.get_realized_summary()
    assert s["count"] == 2  # 1 SELL + 1 RESOLVE
    # SELL: (0.6 - 0.5) × 5 = 0.5; RESOLVE: (1.0 - 0.5) × 5 = 2.5 → total 3.0
    assert s["total_pnl"] == pytest.approx(3.0)
    assert s["total_fees"] > 0  # BUY fee + SELL fee (fees_enabled market)
