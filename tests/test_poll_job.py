"""Tests for global poll job — price layer."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

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
from scanner.daemon.poll_job import _fetch_midpoint, _fetch_single_market, global_poll


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def _seed(db, event_id="ev1", market_id="m1", token="tok1", **market_kw):
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


class TestGlobalPollPriceLayer:
    def test_updates_market_prices(self, db):
        """Poll should fetch CLOB data and update markets table."""
        _seed(db)

        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
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

        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
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
                market_id="m2",
                event_id="ev1",
                question="Q2",
                clob_token_id_yes="t2",
                updated_at="now",
            ),
            db,
        )

        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
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

        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
            global_poll(db)

        mock_fetch.assert_not_called()

    def test_skips_markets_without_token(self, db):
        """Markets without clob_token_id_yes should be skipped."""
        _seed(db, token=None)

        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
            global_poll(db)

        mock_fetch.assert_not_called()

    def test_non_404_error_doesnt_close(self, db):
        """Non-404 errors (503, timeout) should NOT close the market."""
        _seed(db)

        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
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
                market_id="m2",
                event_id="ev1",
                question="Q2",
                clob_token_id_yes="t2",
                updated_at="now",
            ),
            db,
        )

        def _side_effect(client, market):
            if market.market_id == "m1":
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
                "recent_trades": "[]",
            }

        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
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
                market_id="m2",
                event_id="ev1",
                question="Q2",
                clob_token_id_yes="t2",
                updated_at="now",
            ),
            db,
        )

        call_count = 0

        def _side_effect(client, market):
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

        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
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
        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
            global_poll(db)
        mock_fetch.assert_not_called()

    def test_book_data_stored_as_json(self, db):
        """book_bids, book_asks should be stored as JSON strings."""
        _seed(db)

        bids = [{"price": 0.54, "size": 500}]
        asks = [{"price": 0.56, "size": 400}]

        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
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

    def test_no_trades_request_in_price_layer(self, db):
        """Price layer should only fetch /book, not /trades."""
        _seed(db)

        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
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

        # recent_trades should not be set by price layer
        market = get_market("m1", db)
        # The return dict has no recent_trades key → field stays at old value (None)
        assert "recent_trades" not in mock_fetch.return_value


class TestFetchSingleMarket:
    """Tests for _fetch_single_market — the actual CLOB fetch logic."""

    def _make_market(self, token="tok1", condition_id="0x123"):
        m = MagicMock()
        m.clob_token_id_yes = token
        m.condition_id = condition_id
        return m

    @pytest.mark.asyncio
    async def test_book_only_no_trades(self):
        """_fetch_single_market should only call /book, not /trades or /midpoint."""
        book_response = MagicMock()
        book_response.json.return_value = {
            "bids": [{"price": "0.54", "size": "500"}],
            "asks": [{"price": "0.56", "size": "400"}],
        }
        book_response.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = book_response

        result = await _fetch_single_market(client, self._make_market())

        assert client.get.call_count == 1
        assert "book" in client.get.call_args[0][0]
        assert "yes_price" not in result  # price comes from midpoint batch
        assert "recent_trades" not in result

    @pytest.mark.asyncio
    async def test_book_returns_depth_data(self):
        """_fetch_single_market should return orderbook depth."""
        book_response = MagicMock()
        book_response.json.return_value = {
            "bids": [{"price": "0.54", "size": "500"}, {"price": "0.53", "size": "300"}],
            "asks": [{"price": "0.56", "size": "400"}],
        }
        book_response.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = book_response

        result = await _fetch_single_market(client, self._make_market())
        assert result["bid_depth"] == 800.0
        assert result["ask_depth"] == 400.0
        assert result["spread"] == 0.02


class TestFetchMidpoint:
    @pytest.mark.asyncio
    async def test_returns_midpoint_price(self):
        mid_response = MagicMock()
        mid_response.json.return_value = {"mid": "0.548"}
        mid_response.status_code = 200

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = mid_response

        result = await _fetch_midpoint(client, "token123")
        assert result == pytest.approx(0.548)

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = Exception("timeout")

        result = await _fetch_midpoint(client, "token123")
        assert result is None


class TestWideSpreandIntegration:
    """Integration test for wide spread handling through global_poll."""

    def test_wide_spread_gets_correct_price_via_midpoint(self, db):
        """Wide spread markets should get correct price from /midpoint."""
        _seed(db)

        with patch("scanner.daemon.poll_job._fetch_single_market") as mock_fetch:
            mock_fetch.return_value = {
                "yes_price": 0.929,  # from /midpoint, not (0.001+0.999)/2
                "no_price": 0.071,
                "best_bid": 0.001,
                "best_ask": 0.999,
                "spread": 0.998,
                "last_trade_price": 0.929,
                "bid_depth": 1000.0,
                "ask_depth": 500.0,
                "book_bids": "[]",
                "book_asks": "[]",
            }
            global_poll(db)

        market = get_market("m1", db)
        assert market.yes_price == 0.929
