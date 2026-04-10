"""Integration test: full poll cycle without real API calls.

Tests the PricePoller independently of market_states (removed in v2 schema).
"""

from unittest.mock import AsyncMock, patch

import pytest

from scanner.core.config import ScannerConfig
from scanner.core.db import PolilyDB
from scanner.monitor.models import MovementResult
from scanner.monitor.poll import PricePoller
from scanner.monitor.store import append_movement, get_recent_movements


@pytest.fixture
def db(tmp_path):
    _db = PolilyDB(tmp_path / "test.db")
    yield _db
    _db.close()


@pytest.fixture
def config():
    return ScannerConfig()


def _seed_price_history(db, market_id: str, prices: list[float]):
    """Seed movement_log with price history for z-score baseline."""
    for i, price in enumerate(prices):
        prev = prices[i - 1] if i > 0 else price
        append_movement(
            market_id,
            MovementResult(magnitude=5.0, quality=5.0),
            yes_price=price,
            prev_yes_price=prev,
            db=db,
        )


@pytest.mark.asyncio
async def test_full_poll_cycle_no_trigger(db, config):
    """Small price change should not trigger analysis."""
    _seed_price_history(db, "m1", [0.50, 0.51, 0.50, 0.51, 0.50] * 4)

    poller = PricePoller(config=config, db=db)

    with patch.object(poller, "_fetch_market_data", new_callable=AsyncMock) as mock:
        mock.return_value = {
            "yes_price": 0.51,  # tiny move
            "bids": [], "asks": [], "trades": [],
        }
        result = await poller.poll_single("m1", market_type="other",
                                          token_id="tok_1", prev_price=0.50)

    assert result.label in ("noise", "slow_build")
    assert not result.should_trigger(config.movement.magnitude_threshold,
                                      config.movement.quality_threshold)

    # Verify log was written
    entries = get_recent_movements("m1", db, hours=1)
    assert len(entries) > 0


@pytest.mark.asyncio
async def test_full_poll_cycle_with_trigger(db, config):
    """Large price change with volume should trigger analysis."""
    _seed_price_history(db, "m2", [0.40, 0.41, 0.40, 0.41, 0.40] * 4)

    poller = PricePoller(config=config, db=db)

    from scanner.core.models import Trade
    mock_trades = [Trade(price=0.60, size=200, side="BUY") for _ in range(20)]

    with patch.object(poller, "_fetch_market_data", new_callable=AsyncMock) as mock:
        mock.return_value = {
            "yes_price": 0.60,  # big move from 0.40
            "bids": [],
            "asks": [],
            "trades": mock_trades,
        }
        result = await poller.poll_single("m2", market_type="other",
                                          token_id="tok_2", prev_price=0.40)

    assert result.magnitude > 0
    assert result.quality > 0

    # Verify log persisted
    entries = get_recent_movements("m2", db, hours=1)
    last = entries[0]
    assert last["magnitude"] == result.magnitude
    assert last["yes_price"] == 0.60


@pytest.mark.asyncio
async def test_cooldown_prevents_retrigger(db, config):
    """A recently triggered market should not re-trigger during cooldown."""
    # Simulate a recent triggered analysis
    append_movement("m3", MovementResult(magnitude=85.0, quality=75.0),
                    yes_price=0.60, prev_yes_price=0.50,
                    triggered_analysis=True, db=db)

    poller = PricePoller(config=config, db=db)
    assert poller.check_cooldown("m3", cooldown_seconds=1800) is True
    assert poller.check_cooldown("m3", cooldown_seconds=0) is False
