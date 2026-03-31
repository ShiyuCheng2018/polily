"""Tests for market state persistence."""

import tempfile
from pathlib import Path

from scanner.agents.schemas import WatchCondition
from scanner.market_state import (
    MarketState,
    get_market_state,
    get_watched_markets,
    is_passed,
    load_market_states,
    save_market_states,
    set_market_state,
)


class TestMarketState:
    def test_load_nonexistent(self):
        assert load_market_states("/nonexistent/path.json") == {}

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            states = {
                "m1": MarketState(status="pass", updated_at="2026-04-01T00:00:00"),
                "m2": MarketState(status="watch", updated_at="2026-04-01T00:00:00"),
            }
            save_market_states(states, path)
            loaded = load_market_states(path)
            assert len(loaded) == 2
            assert loaded["m1"].status == "pass"
            assert loaded["m2"].status == "watch"

    def test_set_and_get(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            state = MarketState(status="watch", updated_at="2026-04-01T00:00:00")
            set_market_state("m1", state, path)
            result = get_market_state("m1", path)
            assert result is not None
            assert result.status == "watch"

    def test_get_nonexistent(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            assert get_market_state("nope", path) is None

    def test_is_passed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            set_market_state("m1", MarketState(status="pass", updated_at="2026-04-01"), path)
            set_market_state("m2", MarketState(status="watch", updated_at="2026-04-01"), path)
            assert is_passed("m1", path) is True
            assert is_passed("m2", path) is False
            assert is_passed("m3", path) is False

    def test_get_watched_markets(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            set_market_state("m1", MarketState(status="pass", updated_at="2026-04-01"), path)
            set_market_state("m2", MarketState(status="watch", updated_at="2026-04-01"), path)
            set_market_state("m3", MarketState(status="watch", updated_at="2026-04-01"), path)
            watched = get_watched_markets(path)
            assert len(watched) == 2
            assert "m2" in watched
            assert "m3" in watched
            assert "m1" not in watched

    def test_watch_with_conditions(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            state = MarketState(
                status="watch",
                updated_at="2026-04-01",
                watch_conditions=WatchCondition(
                    watch_reason="价格不对",
                    better_entry="YES <= 0.58",
                    trigger_event="BTC 涨到 70K",
                    invalidation="距结算 <12h",
                ),
            )
            set_market_state("m1", state, path)
            loaded = get_market_state("m1", path)
            assert loaded.watch_conditions is not None
            assert loaded.watch_conditions.better_entry == "YES <= 0.58"
