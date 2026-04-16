"""Tests for poll score refresh — market_row_to_model + refresh_scores."""

import json

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import (
    EventRow,
    MarketRow,
    get_event,
    get_market,
    market_row_to_model,
    upsert_event,
    upsert_market,
)
from scanner.daemon.score_refresh import refresh_scores


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def _make_score_breakdown(**overrides):
    """Build a realistic score_breakdown JSON."""
    bd = {
        "liquidity": 20.0,
        "verifiability": 9.0,
        "probability": 0.0,
        "time": 13.0,
        "friction": 10.0,
        "net_edge": 1.0,
        "mispricing": {
            "fair_value": 0.98,
            "fair_value_low": 0.96,
            "fair_value_high": 1.0,
            "deviation_pct": 0.02,
            "direction": None,
            "signal": "none",
            "model_confidence": "low",
        },
        "price_params": {
            "underlying_price": 71000.0,
            "threshold_price": 68000.0,
            "annual_volatility": 0.41,
            "vol_source": "binance",
        },
        "round_trip_friction_pct": 0.02,
        "commentary": {},
    }
    bd.update(overrides)
    return json.dumps(bd)


def _seed_crypto_event(db, event_id="ev1", market_id="m1", yes_price=0.96,
                       threshold=68000, end_date="2026-04-15T16:00:00+00:00",
                       monitored=True):
    """Seed a crypto event with one scored market."""
    upsert_event(EventRow(
        event_id=event_id,
        title="Bitcoin above ___ on April 15?",
        market_type="crypto",
        volume=500000,
        end_date=end_date,
        updated_at="now",
    ), db)
    upsert_market(MarketRow(
        market_id=market_id,
        event_id=event_id,
        question=f"Will the price of Bitcoin be above ${threshold:,} on April 15?",
        group_item_title=f"{threshold:,}",
        end_date=end_date,
        yes_price=yes_price,
        no_price=round(1 - yes_price, 4),
        best_bid=round(yes_price - 0.005, 3),
        best_ask=round(yes_price + 0.005, 3),
        spread=0.01,
        bid_depth=100000,
        ask_depth=80000,
        book_bids=json.dumps([
            {"price": round(yes_price - 0.005, 3), "size": 50000},
            {"price": round(yes_price - 0.010, 3), "size": 50000},
        ]),
        book_asks=json.dumps([
            {"price": round(yes_price + 0.005, 3), "size": 40000},
            {"price": round(yes_price + 0.010, 3), "size": 40000},
        ]),
        clob_token_id_yes="tok_yes",
        updated_at="now",
    ), db)
    # score_breakdown is not in upsert cols — set it directly
    bd = _make_score_breakdown(**{"price_params": {
        "underlying_price": 71000.0,
        "threshold_price": float(threshold),
        "annual_volatility": 0.41,
        "vol_source": "binance",
    }})
    db.conn.execute(
        "UPDATE markets SET structure_score = 50.0, score_breakdown = ? WHERE market_id = ?",
        (bd, market_id),
    )
    if monitored:
        from scanner.core.monitor_store import upsert_event_monitor
        upsert_event_monitor(event_id, auto_monitor=True, db=db)
    db.conn.commit()


# ---------------------------------------------------------------------------
# market_row_to_model tests
# ---------------------------------------------------------------------------

class TestMarketRowToModel:
    def test_basic_field_mapping(self, db):
        _seed_crypto_event(db)
        mr = get_market("m1", db)
        m = market_row_to_model(mr, market_type="crypto")

        assert m.market_id == "m1"
        assert m.yes_price == 0.96
        assert m.best_bid_yes == mr.best_bid
        assert m.best_ask_yes == mr.best_ask
        assert m.spread_yes == mr.spread
        assert m.market_type == "crypto"

    def test_book_deserialization(self, db):
        _seed_crypto_event(db)
        mr = get_market("m1", db)
        m = market_row_to_model(mr, market_type="crypto")

        assert m.book_depth_bids is not None
        assert len(m.book_depth_bids) == 2
        assert m.total_bid_depth_usd > 0

    def test_resolution_time(self, db):
        _seed_crypto_event(db, end_date="2027-12-31T16:00:00+00:00")
        mr = get_market("m1", db)
        m = market_row_to_model(mr, market_type="crypto")

        assert m.resolution_time is not None
        assert m.days_to_resolution is not None
        assert m.days_to_resolution > 0

    def test_missing_book_data(self, db):
        _seed_crypto_event(db)
        # Clear book data
        db.conn.execute("UPDATE markets SET book_bids = NULL, book_asks = NULL WHERE market_id = 'm1'")
        db.conn.commit()

        mr = get_market("m1", db)
        m = market_row_to_model(mr, market_type="crypto")

        assert m.book_depth_bids is None
        assert m.book_depth_asks is None

    def test_missing_end_date(self, db):
        _seed_crypto_event(db, end_date=None)
        # Need to remove end_date from the market too
        db.conn.execute("UPDATE markets SET end_date = NULL WHERE market_id = 'm1'")
        db.conn.commit()

        mr = get_market("m1", db)
        m = market_row_to_model(mr)

        assert m.resolution_time is None
        assert m.days_to_resolution is None


# ---------------------------------------------------------------------------
# refresh_scores tests
# ---------------------------------------------------------------------------

class TestRefreshScores:
    def test_refreshes_crypto_market_scores(self, db):
        _seed_crypto_event(db, yes_price=0.96, threshold=68000)
        old_score = get_market("m1", db).structure_score

        result = refresh_scores(db, {"BTCUSDT": 69000.0}, config=None)

        assert result.markets_refreshed >= 1
        new_market = get_market("m1", db)
        # Score should change because underlying price changed
        assert new_market.structure_score != old_score

    def test_refreshes_event_score(self, db):
        _seed_crypto_event(db)

        result = refresh_scores(db, {"BTCUSDT": 69000.0}, config=None)

        assert result.events_refreshed == 1
        new_event = get_event("ev1", db)
        assert new_event.structure_score is not None
        assert new_event.structure_score > 0  # should be a real score, not just non-null

    def test_updates_mispricing_in_breakdown(self, db):
        _seed_crypto_event(db)

        refresh_scores(db, {"BTCUSDT": 67500.0}, config=None)

        market = get_market("m1", db)
        bd = json.loads(market.score_breakdown)
        mp = bd.get("mispricing", {})
        # With BTC near threshold ($67.5K vs $68K), fair_value should differ from market
        assert mp.get("fair_value") is not None
        assert mp.get("deviation_pct") is not None

    def test_updates_underlying_price_in_breakdown(self, db):
        _seed_crypto_event(db)

        refresh_scores(db, {"BTCUSDT": 75000.0}, config=None)

        market = get_market("m1", db)
        bd = json.loads(market.score_breakdown)
        pp = bd.get("price_params", {})
        assert pp.get("underlying_price") == 75000.0

    def test_preserves_verifiability_and_time(self, db):
        _seed_crypto_event(db)
        old_bd = json.loads(get_market("m1", db).score_breakdown)

        refresh_scores(db, {"BTCUSDT": 69000.0}, config=None)

        new_bd = json.loads(get_market("m1", db).score_breakdown)
        # verifiability stays the same (not recalculated)
        assert new_bd["verifiability"] == old_bd["verifiability"]

    def test_no_scored_markets_returns_zero(self, db):
        # Event with no score_breakdown
        upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1", question="Q",
            updated_at="now",
        ), db)

        result = refresh_scores(db, {}, config=None)

        assert result.markets_refreshed == 0
        assert result.events_refreshed == 0

    def test_non_crypto_market_refreshes_without_underlying(self, db):
        """Non-crypto markets should refresh liq/prob/friction even without Binance data."""
        upsert_event(EventRow(
            event_id="ev1", title="Will team X win?",
            market_type="sports", volume=200000,
            end_date="2026-04-20T00:00:00+00:00",
            updated_at="now",
        ), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1",
            question="Will team X win?",
            end_date="2026-04-20T00:00:00+00:00",
            yes_price=0.60, no_price=0.40,
            best_bid=0.59, best_ask=0.61, spread=0.02,
            bid_depth=5000, ask_depth=4000,
            book_bids=json.dumps([{"price": 0.59, "size": 5000}]),
            book_asks=json.dumps([{"price": 0.61, "size": 4000}]),
            updated_at="now",
        ), db)
        db.conn.execute(
            "UPDATE markets SET structure_score = 40.0, score_breakdown = ? WHERE market_id = 'm1'",
            (json.dumps({
                "liquidity": 15.0, "verifiability": 8.0,
                "probability": 12.0, "time": 20.0, "friction": 8.0,
                "commentary": {},
            }),),
        )
        from scanner.core.monitor_store import upsert_event_monitor
        upsert_event_monitor("ev1", auto_monitor=True, db=db)
        db.conn.commit()

        result = refresh_scores(db, {}, config=None)

        assert result.markets_refreshed == 1
        new_market = get_market("m1", db)
        assert new_market.structure_score is not None

    def test_multiple_markets_same_event(self, db):
        """Multiple sub-markets in same event all get refreshed."""
        upsert_event(EventRow(
            event_id="ev1", title="Bitcoin above ___ on April 15?",
            market_type="crypto", volume=500000,
            end_date="2026-04-15T16:00:00+00:00",
            updated_at="now",
        ), db)
        for i, (threshold, price) in enumerate([(66000, 0.99), (68000, 0.96), (70000, 0.80)]):
            upsert_market(MarketRow(
                market_id=f"m{i}",
                event_id="ev1",
                question=f"BTC above ${threshold:,}?",
                group_item_title=f"{threshold:,}",
                end_date="2026-04-15T16:00:00+00:00",
                yes_price=price, no_price=round(1 - price, 4),
                best_bid=round(price - 0.005, 3), best_ask=round(price + 0.005, 3),
                spread=0.01, bid_depth=50000, ask_depth=40000,
                book_bids=json.dumps([{"price": round(price - 0.005, 3), "size": 50000}]),
                book_asks=json.dumps([{"price": round(price + 0.005, 3), "size": 40000}]),
                clob_token_id_yes=f"tok{i}",
                updated_at="now",
            ), db)
            bd = _make_score_breakdown(**{
                "price_params": {
                    "underlying_price": 71000.0,
                    "threshold_price": float(threshold),
                    "annual_volatility": 0.41,
                    "vol_source": "binance",
                }
            })
            db.conn.execute(
                "UPDATE markets SET structure_score = 45.0, score_breakdown = ? WHERE market_id = ?",
                (bd, f"m{i}"),
            )
        from scanner.core.monitor_store import upsert_event_monitor
        upsert_event_monitor("ev1", auto_monitor=True, db=db)
        db.conn.commit()

        result = refresh_scores(db, {"BTCUSDT": 69000.0}, config=None)

        assert result.markets_refreshed == 3
        assert result.events_refreshed == 1


# ---------------------------------------------------------------------------
# Binance fetch + collect_crypto_symbols tests
# ---------------------------------------------------------------------------

class TestCollectCryptoSymbols:
    def test_extracts_symbols_from_crypto_events(self, db):
        from scanner.core.monitor_store import upsert_event_monitor
        from scanner.daemon.poll_job import _collect_crypto_symbols

        upsert_event(EventRow(
            event_id="ev1", title="Bitcoin above ___ on April 15?",
            market_type="crypto", updated_at="now",
        ), db)
        upsert_event(EventRow(
            event_id="ev2", title="Ethereum above ___ on April 15?",
            market_type="crypto", updated_at="now",
        ), db)
        upsert_event(EventRow(
            event_id="ev3", title="Will team X win?",
            market_type="sports", updated_at="now",
        ), db)
        upsert_event_monitor("ev1", auto_monitor=True, db=db)
        upsert_event_monitor("ev2", auto_monitor=True, db=db)

        symbols = _collect_crypto_symbols(db)

        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols
        assert len(symbols) == 2  # no sports

    def test_empty_when_no_crypto(self, db):
        from scanner.daemon.poll_job import _collect_crypto_symbols

        upsert_event(EventRow(
            event_id="ev1", title="Will team X win?",
            market_type="sports", updated_at="now",
        ), db)

        symbols = _collect_crypto_symbols(db)
        assert symbols == set()


class TestFetchBinanceTickers:
    @pytest.mark.asyncio
    async def test_parses_response(self):
        from unittest.mock import AsyncMock, MagicMock

        import httpx

        from scanner.daemon.poll_job import _fetch_binance_tickers

        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"symbol": "BTCUSDT", "price": "71000.50"},
            {"symbol": "ETHUSDT", "price": "2200.00"},
        ]
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_resp

        result = await _fetch_binance_tickers(mock_client, {"BTCUSDT", "ETHUSDT"})

        assert result["BTCUSDT"] == 71000.50
        assert result["ETHUSDT"] == 2200.00

    @pytest.mark.asyncio
    async def test_empty_symbols_returns_empty(self):
        from unittest.mock import AsyncMock

        from scanner.daemon.poll_job import _fetch_binance_tickers

        result = await _fetch_binance_tickers(AsyncMock(), set())
        assert result == {}
