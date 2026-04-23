"""Task 3.1: get_open_trades returns positions in paper_trades dict shape.

TUI's paper_status view reads t["id"], t["market_id"], t["event_id"],
t["side"], t["title"], t["entry_price"], t["position_size_usd"] and
derives `shares = size / entry`. Shape shim at the service layer keeps
the view untouched while the underlying source moves to `positions`.
"""

from unittest.mock import patch

import pytest

from polily.core.config import PolilyConfig
from polily.core.db import PolilyDB
from polily.tui.service import PolilyService


@pytest.fixture
def svc(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    db.conn.executescript(
        """
        INSERT INTO events (event_id,title,updated_at)
            VALUES ('e1','E1','t');
        INSERT INTO markets (market_id,event_id,question,clob_token_id_yes,clob_token_id_no,yes_price,updated_at)
            VALUES ('m1','e1','Will X?','tok_yes','tok_no',0.5,'t');
        INSERT INTO markets (market_id,event_id,question,clob_token_id_yes,clob_token_id_no,yes_price,updated_at)
            VALUES ('m2','e1','Will Y?','tok2_yes','tok2_no',0.3,'t');
        """
    )
    # v0.8.0: PolilyService.execute_buy/sell require auto_monitor=1.
    from polily.core.monitor_store import upsert_event_monitor
    upsert_event_monitor("e1", auto_monitor=True, db=db)
    db.conn.commit()
    return PolilyService(config=PolilyConfig(), db=db)


def _mock_price(value: float):
    return patch(
        "polily.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=value,
    )


def test_get_open_trades_empty_when_no_positions(svc):
    """Empty positions → empty result."""
    assert svc.get_open_trades() == []


def test_get_open_trades_reads_positions_with_shape_shim(svc):
    """get_open_trades returns positions as paper_trades-compatible dicts."""
    with _mock_price(0.5):
        svc.execute_buy(market_id="m1", side="yes", shares=20.0)

    trades = svc.get_open_trades()
    assert len(trades) == 1
    t = trades[0]

    # Composite synthetic row key preserves DataTable.add_row(key=...) semantics.
    assert t["id"] == "m1:yes"
    assert t["market_id"] == "m1"
    assert t["event_id"] == "e1"
    assert t["side"] == "yes"
    assert t["title"] == "Will X?"

    # entry_price = avg_cost (weighted-avg over adds); position_size_usd = cost_basis.
    assert t["entry_price"] == pytest.approx(0.5)
    assert t["position_size_usd"] == pytest.approx(10.0)

    # View derives `shares = size / entry` — must round-trip to actual shares.
    assert t["position_size_usd"] / t["entry_price"] == pytest.approx(20.0)


def test_get_open_trades_id_unique_per_side(svc):
    """YES and NO on the same market yield distinct row keys."""
    with _mock_price(0.5):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    with _mock_price(0.5):
        svc.execute_buy(market_id="m1", side="no", shares=10.0)

    trades = svc.get_open_trades()
    ids = {t["id"] for t in trades}
    assert ids == {"m1:yes", "m1:no"}


def test_get_open_trades_multiple_markets(svc):
    """Multiple positions across markets all surface with correct shape."""
    with _mock_price(0.5):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    with _mock_price(0.3):
        svc.execute_buy(market_id="m2", side="yes", shares=5.0)

    trades = svc.get_open_trades()
    by_id = {t["id"]: t for t in trades}
    assert set(by_id.keys()) == {"m1:yes", "m2:yes"}
    assert by_id["m2:yes"]["title"] == "Will Y?"
    assert by_id["m2:yes"]["position_size_usd"] == pytest.approx(1.5)


def test_shares_roundtrip_after_weighted_avg_add(svc):
    """Invariant: cost_basis / avg_cost == true shares, even after weighted-avg add.

    View derives `shares = size / entry` — must equal the actual position shares
    within float rounding.
    """
    with _mock_price(0.5):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    with _mock_price(0.7):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)

    trades = svc.get_open_trades()
    assert len(trades) == 1
    t = trades[0]
    # True shares = 20. Derived shares = cost_basis / avg_cost should match.
    derived_shares = t["position_size_usd"] / t["entry_price"]
    assert derived_shares == pytest.approx(20.0)
    # avg_cost = (10*0.5 + 10*0.7) / 20 = 0.6
    assert t["entry_price"] == pytest.approx(0.6)


def test_shares_roundtrip_after_partial_sell(svc):
    """Invariant holds after partial sell (avg_cost preserved, cost_basis rescaled)."""
    with _mock_price(0.5):
        svc.execute_buy(market_id="m1", side="yes", shares=20.0)
    with _mock_price(0.6):
        svc.execute_sell(market_id="m1", side="yes", shares=5.0)

    trades = svc.get_open_trades()
    assert len(trades) == 1
    t = trades[0]
    derived_shares = t["position_size_usd"] / t["entry_price"]
    assert derived_shares == pytest.approx(15.0)
    # avg_cost preserved on sell
    assert t["entry_price"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_paper_status_refresh_data_picks_up_new_positions(svc, tmp_path):
    """Regression: refresh_data must re-query positions.

    Bug: refresh_data used a cached self._trades set at mount. If a position
    was deleted by auto-resolution (or added by a future path that keeps the
    view mounted), the heartbeat-triggered refresh would iterate stale rows.
    """
    from textual.app import App
    from textual.screen import Screen
    from textual.widgets import DataTable

    from polily.tui.views.paper_status import PaperStatusView

    # Seed one position so on_mount has something to show.
    with _mock_price(0.5):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)

    class _HostScreen(Screen):
        def __init__(self, view):
            super().__init__()
            self._view = view

        def compose(self):
            yield self._view

    class _Host(App):
        def __init__(self, service):
            super().__init__()
            self._service = service

        def on_mount(self):
            self.push_screen(_HostScreen(PaperStatusView(self._service)))

    host = _Host(svc)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        view = host.screen.query_one(PaperStatusView)
        assert len(view._trades) == 1  # seeded position

        # Close the position behind the view's back (simulates resolution).
        svc.db.conn.execute("DELETE FROM positions")
        svc.db.conn.commit()

        # refresh_data must re-read and see the deletion.
        view.refresh_data()
        await pilot.pause()
        assert view._trades == []
        table = view.query_one("#portfolio-table", DataTable)
        assert table.row_count == 0
