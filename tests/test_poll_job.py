"""Tests for global poll job — price layer."""
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import (
    EventRow,
    MarketRow,
    get_event,
    get_market,
    upsert_event,
    upsert_market,
)
from scanner.core.monitor_store import upsert_event_monitor
from scanner.daemon.poll_job import global_poll


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def _seed(db, event_id="ev1", market_id="m1", token="tok1", monitored=True, **market_kw):
    upsert_event(EventRow(event_id=event_id, title="E", updated_at="now"), db)
    defaults = dict(
        market_id=market_id,
        event_id=event_id,
        question="Q",
        clob_token_id_yes=token,
        condition_id="0x123",
        updated_at="now",
    )
    defaults.update(market_kw)
    upsert_market(MarketRow(**defaults), db)
    if monitored:
        upsert_event_monitor(event_id, auto_monitor=True, db=db)


class TestGlobalPollPriceLayer:
    def test_updates_market_prices(self, db):
        """Poll should fetch CLOB data and update markets table."""
        _seed(db)

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            mock_fetch.return_value = {
                "yes_price": 0.55,
                "no_price": 0.45,
                "best_bid": 0.54,
                "best_ask": 0.56,
                "spread": 0.02,
                "last_trade_price": 0.55,
                "bid_depth": 800.0,
                "ask_depth": 600.0,
                "book_bids": json.dumps(
                    [{"price": 0.54, "size": 500}, {"price": 0.53, "size": 300}]
                ),
                "book_asks": json.dumps(
                    [{"price": 0.56, "size": 400}, {"price": 0.57, "size": 200}]
                ),
                "recent_trades": json.dumps(
                    [{"price": 0.55, "size": 100, "side": "BUY"}]
                ),
            }
            global_poll(db)

        market = get_market("m1", db)
        assert market.yes_price == 0.55
        assert market.best_bid == 0.54
        assert market.bid_depth == 800.0
        assert market.book_bids is not None

    def test_handles_404_closes_market(self, db):
        """404 from CLOB should mark market as closed."""
        _seed(db)

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            mock_fetch.side_effect = httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
            global_poll(db)

        market = get_market("m1", db)
        assert market.closed == 1

    def test_closes_event_when_all_sub_markets_closed(self, db):
        """When all sub-markets 404, event should close."""
        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)
        upsert_market(
            MarketRow(
                market_id="m1", event_id="ev1", question="Q1",
                clob_token_id_yes="t1", updated_at="now",
            ), db,
        )
        upsert_market(
            MarketRow(
                market_id="m2", event_id="ev1", question="Q2",
                clob_token_id_yes="t2", updated_at="now",
            ), db,
        )
        upsert_event_monitor("ev1", auto_monitor=True, db=db)

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            mock_fetch.side_effect = httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
            global_poll(db)

        event = get_event("ev1", db)
        assert event.closed == 1

    def test_skips_closed_markets(self, db):
        """Markets with closed=1 should not be fetched."""
        _seed(db, closed=1)

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            global_poll(db)

        mock_fetch.assert_not_called()

    def test_skips_markets_without_token(self, db):
        """Markets without clob_token_id_yes should be skipped."""
        _seed(db, token=None)

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            global_poll(db)

        mock_fetch.assert_not_called()

    def test_non_404_error_doesnt_close(self, db):
        """Non-404 errors (503, timeout) should NOT close the market."""
        _seed(db)

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            mock_fetch.side_effect = httpx.HTTPStatusError(
                "Service Unavailable",
                request=MagicMock(),
                response=MagicMock(status_code=503),
            )
            global_poll(db)

        market = get_market("m1", db)
        assert market.closed == 0

    def test_partial_event_close_doesnt_close_event(self, db):
        """If only some sub-markets 404, event should NOT close."""
        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)
        upsert_market(
            MarketRow(
                market_id="m1", event_id="ev1", question="Q1",
                clob_token_id_yes="t1", updated_at="now",
            ), db,
        )
        upsert_market(
            MarketRow(
                market_id="m2", event_id="ev1", question="Q2",
                clob_token_id_yes="t2", updated_at="now",
            ), db,
        )
        upsert_event_monitor("ev1", auto_monitor=True, db=db)

        def _side_effect(client, token_id):
            if token_id == "t1":  # m1's token
                raise httpx.HTTPStatusError(
                    "Not Found",
                    request=MagicMock(),
                    response=MagicMock(status_code=404),
                )
            return {
                "yes_price": 0.50,
                "no_price": 0.50,
                "best_bid": 0.49,
                "best_ask": 0.51,
                "spread": 0.02,
                "last_trade_price": 0.50,
                "bid_depth": 100.0,
                "ask_depth": 100.0,
                "book_bids": "[]",
                "book_asks": "[]",
            }

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            mock_fetch.side_effect = _side_effect
            global_poll(db)

        # m1 closed, m2 still open → event stays open
        m1 = get_market("m1", db)
        m2 = get_market("m2", db)
        assert m1.closed == 1
        assert m2.closed == 0
        event = get_event("ev1", db)
        assert event.closed == 0

    def test_multiple_markets_all_updated(self, db):
        """All active markets should be fetched and updated in one poll cycle."""
        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)
        upsert_market(
            MarketRow(
                market_id="m1",
                event_id="ev1",
                question="Q1",
                clob_token_id_yes="t1",
                updated_at="now",
            ),
            db,
        )
        upsert_market(
            MarketRow(
                market_id="m2", event_id="ev1", question="Q2",
                clob_token_id_yes="t2", updated_at="now",
            ), db,
        )
        upsert_event_monitor("ev1", auto_monitor=True, db=db)

        call_count = 0

        def _side_effect(client, token_id):
            nonlocal call_count
            call_count += 1
            price = 0.50 + call_count * 0.01
            return {
                "yes_price": price,
                "no_price": round(1 - price, 2),
                "best_bid": round(price - 0.01, 2),
                "best_ask": round(price + 0.01, 2),
                "spread": 0.02,
                "last_trade_price": price,
                "bid_depth": 100.0,
                "ask_depth": 100.0,
                "book_bids": "[]",
                "book_asks": "[]",
                "recent_trades": "[]",
            }

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            mock_fetch.side_effect = _side_effect
            global_poll(db)

        assert call_count == 2
        m1 = get_market("m1", db)
        m2 = get_market("m2", db)
        assert m1.yes_price is not None
        assert m2.yes_price is not None
        assert m1.yes_price != m2.yes_price  # different prices

    def test_no_active_markets_is_noop(self, db):
        """Poll with no active markets should not error."""
        # Empty DB — no markets at all
        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            global_poll(db)
        mock_fetch.assert_not_called()

    def test_book_data_stored_as_json(self, db):
        """book_bids, book_asks should be stored as JSON strings."""
        _seed(db)

        bids = [{"price": 0.54, "size": 500}]
        asks = [{"price": 0.56, "size": 400}]

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            mock_fetch.return_value = {
                "yes_price": 0.55,
                "no_price": 0.45,
                "best_bid": 0.54,
                "best_ask": 0.56,
                "spread": 0.02,
                "last_trade_price": 0.55,
                "bid_depth": 500.0,
                "ask_depth": 400.0,
                "book_bids": json.dumps(bids),
                "book_asks": json.dumps(asks),
            }
            global_poll(db)

        market = get_market("m1", db)
        assert json.loads(market.book_bids) == bids
        assert json.loads(market.book_asks) == asks

    def test_clob_fetch_does_not_include_trades(self, db):
        """fetch_clob_market_data returns price/book data, not trades (trades come from Data API separately)."""
        _seed(db)

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            mock_fetch.return_value = {
                "yes_price": 0.55,
                "no_price": 0.45,
                "best_bid": 0.54,
                "best_ask": 0.56,
                "spread": 0.02,
                "last_trade_price": 0.55,
                "bid_depth": 500.0,
                "ask_depth": 400.0,
                "book_bids": "[]",
                "book_asks": "[]",
            }
            global_poll(db)

        # CLOB fetch result has no recent_trades key — trades come from _fetch_trades_batch
        assert "recent_trades" not in mock_fetch.return_value


class TestWideSpreadIntegration:
    """Integration test for wide spread handling through global_poll."""

    def test_negRisk_gets_correct_bid_ask_from_price_endpoint(self, db):
        """negRisk markets should get correct bid/ask from /price, not /book."""
        _seed(db)

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            mock_fetch.return_value = {
                "yes_price": 0.929,   # from /midpoint
                "no_price": 0.071,
                "best_bid": 0.925,    # from /price SELL (real bid)
                "best_ask": 0.935,    # from /price BUY (real ask)
                "spread": 0.01,       # real spread, not 0.998
                "last_trade_price": 0.929,
                "bid_depth": 1000.0,
                "ask_depth": 500.0,
                "book_bids": "[]",
                "book_asks": "[]",
            }
            global_poll(db)

        market = get_market("m1", db)
        assert market.yes_price == 0.929
        assert market.best_bid == 0.925
        assert market.best_ask == 0.935
        assert market.spread == 0.01


class TestPollOnlyMonitoredEvents:
    """Poll should only fetch markets from monitored events."""

    def test_only_monitored_markets_fetched(self, db):
        """Markets from non-monitored events should NOT be fetched."""
        # ev1 monitored, ev2 not
        _seed(db, "ev1", "m1", token="t1")
        _seed(db, "ev2", "m2", token="t2", monitored=False)

        call_count = 0

        def _side_effect(client, token_id):
            nonlocal call_count
            call_count += 1
            return {
                "yes_price": 0.50, "no_price": 0.50,
                "best_bid": 0.49, "best_ask": 0.51, "spread": 0.02,
                "last_trade_price": 0.50,
                "bid_depth": 100.0, "ask_depth": 100.0,
                "book_bids": "[]", "book_asks": "[]",
            }

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            mock_fetch.side_effect = _side_effect
            global_poll(db)

        assert call_count == 1  # only ev1's market
        m1 = get_market("m1", db)
        m2 = get_market("m2", db)
        assert m1.yes_price == 0.50  # updated
        assert m2.yes_price is None  # NOT updated

    def test_no_monitored_events_is_noop(self, db):
        """If no events are monitored, poll should not fetch anything."""
        _seed(db, "ev1", "m1", token="t1", monitored=False)

        with patch("scanner.core.clob.fetch_clob_market_data") as mock_fetch:
            global_poll(db)

        mock_fetch.assert_not_called()
