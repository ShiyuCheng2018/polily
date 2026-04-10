from unittest.mock import AsyncMock, patch

import pytest

from scanner.core.config import ScannerConfig
from scanner.core.db import PolilyDB
from scanner.monitor.models import MovementResult
from scanner.monitor.poll import PricePoller
from scanner.monitor.store import append_movement


@pytest.fixture
def db(tmp_path):
    _db = PolilyDB(tmp_path / "test.db")
    yield _db
    _db.close()


def test_poller_init(db):
    config = ScannerConfig()
    poller = PricePoller(config=config, db=db)
    assert poller is not None


@pytest.mark.asyncio
async def test_poll_single_market_returns_result(db):
    config = ScannerConfig()
    poller = PricePoller(config=config, db=db)

    from scanner.core.models import BookLevel, Trade

    with patch.object(poller, "_fetch_market_data", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {
            "yes_price": 0.55,
            "bids": [BookLevel(price=0.54, size=500)],
            "asks": [BookLevel(price=0.56, size=500)],
            "trades": [Trade(price=0.55, size=100, side="BUY")],
        }
        # Seed some price history
        for price in [0.50, 0.51, 0.50, 0.52, 0.51]:
            append_movement("m1", MovementResult(magnitude=10.0, quality=10.0),
                           yes_price=price, prev_yes_price=price - 0.01, db=db)

        result = await poller.poll_single("m1", market_type="crypto",
                                          token_id="tok_1", prev_price=0.50)
        assert isinstance(result, MovementResult)
        assert result.magnitude >= 0
        assert result.quality >= 0


@pytest.mark.asyncio
async def test_poll_single_respects_cooldown(db):
    config = ScannerConfig()
    poller = PricePoller(config=config, db=db)

    append_movement("m1", MovementResult(magnitude=80.0, quality=70.0),
                    yes_price=0.55, prev_yes_price=0.50,
                    triggered_analysis=True, db=db)

    result = poller.check_cooldown("m1", cooldown_seconds=1800)
    assert result is True  # in cooldown


@pytest.mark.asyncio
async def test_crypto_enrichment_adds_fair_value(db):
    config = ScannerConfig()
    poller = PricePoller(config=config, db=db)

    with patch.object(poller, "_fetch_market_data", new_callable=AsyncMock) as mock_fetch, \
         patch.object(poller, "_fetch_crypto_signals", new_callable=AsyncMock) as mock_crypto:
        mock_fetch.return_value = {
            "yes_price": 0.55,
            "bids": [], "asks": [], "trades": [],
        }
        mock_crypto.return_value = {
            "fair_value_divergence": 0.12,
            "underlying_z_score": 2.5,
            "cross_divergence": 0.3,
        }
        result = await poller.poll_single("m1", market_type="crypto",
                                          token_id="tok_1", prev_price=0.50,
                                          market_title="BTC above $100K?")
        assert result.signals.fair_value_divergence == 0.12
        assert result.signals.underlying_z_score == 2.5


def test_check_daily_limit(db):
    config = ScannerConfig()
    poller = PricePoller(config=config, db=db)

    # No triggered analyses — should not be at limit
    assert poller.check_daily_limit("m1") is False

    # Add triggered analyses up to the limit
    for _i in range(config.movement.daily_analysis_limit):
        append_movement("m1", MovementResult(magnitude=80.0, quality=70.0),
                        yes_price=0.55, prev_yes_price=0.50,
                        triggered_analysis=True, db=db)

    assert poller.check_daily_limit("m1") is True
