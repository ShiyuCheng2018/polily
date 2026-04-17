"""Tests for auto-resolution wired into poll_job.

Unit tests cover the helper `_resolve_closed_market_if_position` in isolation
(mocking the Gamma fetch). Integration tests exercise `global_poll` end-to-end:
CLOB 404 → mark_market_closed → Gamma fetch gated on "has positions?" →
ResolutionHandler settles.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.monitor_store import upsert_event_monitor
from scanner.core.positions import PositionManager
from scanner.core.wallet import WalletService
from scanner.daemon import poll_job
from scanner.daemon.resolution import ResolutionHandler


@pytest.fixture(autouse=True)
def _reset_poller_ctx():
    """Prevent `_ctx` leaking between tests — test order could otherwise
    yield stale WalletService/PositionManager references bound to closed
    DBs (this whole file populates _ctx via init_poller in multiple tests).
    """
    poll_job._ctx = None
    yield
    poll_job._ctx = None


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


@pytest.fixture
def services(db):
    wallet = WalletService(db)
    positions = PositionManager(db)
    resolver = ResolutionHandler(db, wallet, positions)
    return wallet, positions, resolver


def _seed(db, event_id="e1", market_id="m1", token="tok1", monitored=True):
    upsert_event(EventRow(event_id=event_id, title="E", updated_at="now"), db)
    upsert_market(
        MarketRow(
            market_id=market_id,
            event_id=event_id,
            question="Q",
            clob_token_id_yes=token,
            updated_at="now",
        ),
        db,
    )
    if monitored:
        upsert_event_monitor(event_id, auto_monitor=True, db=db)


# --- helper: _resolve_closed_market_if_position -------------------------


@pytest.mark.asyncio
async def test_helper_skips_when_no_positions(db, services):
    """No positions on the market → Gamma fetch must NOT happen."""
    wallet, positions, resolver = services
    _seed(db)

    with patch.object(poll_job, "_fetch_gamma_market", new=AsyncMock()) as mock_fetch:
        await poll_job._resolve_closed_market_if_position(
            "m1", db, wallet, positions, resolver,
        )
    mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_helper_settles_when_position_and_gamma_yes_won(db, services):
    wallet, positions, resolver = services
    _seed(db)
    positions.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10, price=0.5
    )
    cash_before = wallet.get_cash()

    gamma_response = {"outcomePrices": '["1", "0"]', "closed": True}
    with patch.object(
        poll_job, "_fetch_gamma_market", new=AsyncMock(return_value=gamma_response)
    ):
        await poll_job._resolve_closed_market_if_position(
            "m1", db, wallet, positions, resolver,
        )

    assert positions.get_position("m1", "yes") is None
    assert wallet.get_cash() == pytest.approx(cash_before + 10.0)
    assert (
        db.conn.execute(
            "SELECT resolved_outcome FROM markets WHERE market_id='m1'"
        ).fetchone()["resolved_outcome"]
        == "yes"
    )


@pytest.mark.asyncio
async def test_helper_writes_poll_log_audit_line_on_settlement(db, services):
    """poll.log must carry a human-readable resolution line per settlement —
    operator visibility for 'did auto-resolve fire for market X?' queries."""
    wallet, positions, resolver = services
    _seed(db)
    positions.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10, price=0.5
    )

    # Patch the poll-log to capture calls without touching the real file.
    fake_log = MagicMock()
    with patch.object(poll_job, "_get_poll_log", return_value=fake_log), \
         patch.object(
             poll_job, "_fetch_gamma_market",
             new=AsyncMock(return_value={"outcomePrices": '["1", "0"]'}),
         ):
        await poll_job._resolve_closed_market_if_position(
            "m1", db, wallet, positions, resolver,
        )

    # At least one info() call mentioning the market_id, winner, and credit.
    logged = " ".join(
        call.args[0] if call.args else "" for call in fake_log.info.call_args_list
    )
    assert "m1" in logged
    assert "yes" in logged
    assert "$10.00" in logged


@pytest.mark.asyncio
async def test_helper_does_not_log_when_no_positions(db, services):
    """Skip log noise when resolution is a no-op (zero positions settled)."""
    wallet, positions, resolver = services
    _seed(db)  # market but no positions

    fake_log = MagicMock()
    with patch.object(poll_job, "_get_poll_log", return_value=fake_log):
        await poll_job._resolve_closed_market_if_position(
            "m1", db, wallet, positions, resolver,
        )
    fake_log.info.assert_not_called()


@pytest.mark.asyncio
async def test_helper_settles_with_unnormalized_decimal_strings(db, services):
    """Gamma sometimes returns ["1.0", "0.0"] — derive_winner must still classify."""
    wallet, positions, resolver = services
    _seed(db)
    positions.add_shares(
        market_id="m1", side="no", event_id="e1", title="Q", shares=5, price=0.4
    )

    gamma_response = {"outcomePrices": '["0.0", "1.0"]'}
    with patch.object(
        poll_job, "_fetch_gamma_market", new=AsyncMock(return_value=gamma_response)
    ):
        await poll_job._resolve_closed_market_if_position(
            "m1", db, wallet, positions, resolver,
        )

    # NO won → payout $1 × 5 shares = $5 credited.
    assert positions.get_position("m1", "no") is None
    txs = wallet.list_transactions(tx_type="RESOLVE")
    assert len(txs) == 1
    assert txs[0]["amount_usd"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_helper_skips_when_gamma_says_unresolved(db, services):
    """Gamma still in UMA dispute window → outcomePrices=["0","0"] → no settlement."""
    wallet, positions, resolver = services
    _seed(db)
    positions.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10, price=0.5
    )
    cash_before = wallet.get_cash()

    with patch.object(
        poll_job,
        "_fetch_gamma_market",
        new=AsyncMock(return_value={"outcomePrices": '["0", "0"]'}),
    ):
        await poll_job._resolve_closed_market_if_position(
            "m1", db, wallet, positions, resolver,
        )

    # No settlement — position preserved, cash unchanged, no ledger row.
    assert positions.get_position("m1", "yes") is not None
    assert wallet.get_cash() == cash_before
    assert wallet.list_transactions(tx_type="RESOLVE") == []


@pytest.mark.asyncio
async def test_helper_swallows_gamma_http_failure(db, services):
    """If Gamma fetch returns None (timeout/5xx/404), helper logs and returns
    cleanly — next tick retries."""
    wallet, positions, resolver = services
    _seed(db)
    positions.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10, price=0.5
    )
    cash_before = wallet.get_cash()

    with patch.object(
        poll_job, "_fetch_gamma_market", new=AsyncMock(return_value=None)
    ):
        await poll_job._resolve_closed_market_if_position(
            "m1", db, wallet, positions, resolver,
        )

    assert positions.get_position("m1", "yes") is not None
    assert wallet.get_cash() == cash_before


@pytest.mark.asyncio
async def test_helper_handles_list_outcome_prices(db, services):
    """Gamma may occasionally return outcomePrices as a list (not JSON string)."""
    wallet, positions, resolver = services
    _seed(db)
    positions.add_shares(
        market_id="m1", side="yes", event_id="e1", title="Q", shares=10, price=0.5
    )

    with patch.object(
        poll_job,
        "_fetch_gamma_market",
        new=AsyncMock(return_value={"outcomePrices": ["1", "0"]}),
    ):
        await poll_job._resolve_closed_market_if_position(
            "m1", db, wallet, positions, resolver,
        )
    assert positions.get_position("m1", "yes") is None


# --- _fetch_gamma_market (wraps httpx) ----------------------------------


@pytest.mark.asyncio
async def test_fetch_gamma_market_returns_dict_on_200():
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json = MagicMock(
        return_value={"outcomePrices": '["1","0"]', "closed": True}
    )
    # httpx.AsyncClient is used as a context manager.
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    with patch("httpx.AsyncClient", return_value=fake_client):
        data = await poll_job._fetch_gamma_market("m1")
    assert data == {"outcomePrices": '["1","0"]', "closed": True}


@pytest.mark.asyncio
async def test_fetch_gamma_market_returns_none_on_http_error():
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(status_code=500)
        )
    )
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    with patch("httpx.AsyncClient", return_value=fake_client):
        data = await poll_job._fetch_gamma_market("m1")
    assert data is None


@pytest.mark.asyncio
async def test_fetch_gamma_market_returns_none_on_timeout():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.side_effect = httpx.TimeoutException("timed out")
        data = await poll_job._fetch_gamma_market("m1")
    assert data is None


# --- init_poller signature (required params) ----------------------------


def test_init_poller_requires_wallet_positions_resolver(db, services):
    """init_poller must enforce wallet/positions/resolver as required args."""
    wallet, positions, resolver = services
    # Missing required args raises TypeError.
    with pytest.raises(TypeError):
        poll_job.init_poller(db=db)  # type: ignore[call-arg]
    # Happy path: all required args provided.
    poll_job.init_poller(
        db=db, wallet=wallet, positions=positions, resolver=resolver
    )
    assert poll_job._ctx is not None
    assert poll_job._ctx.wallet is wallet
    assert poll_job._ctx.resolver is resolver


# --- Integration: global_poll end-to-end --------------------------------


class TestGlobalPollResolutionIntegration:
    def test_404_with_position_triggers_resolution(self, db, services):
        """CLOB 404 → mark_market_closed → Gamma fetch → settle."""
        wallet, positions, resolver = services
        _seed(db)
        positions.add_shares(
            market_id="m1", side="yes", event_id="e1", title="Q",
            shares=10, price=0.5,
        )
        poll_job.init_poller(
            db=db, wallet=wallet, positions=positions, resolver=resolver,
        )
        cash_before = wallet.get_cash()

        with (
            patch("scanner.core.clob.fetch_clob_market_data") as mock_clob,
            patch.object(
                poll_job,
                "_fetch_gamma_market",
                new=AsyncMock(return_value={"outcomePrices": '["1", "0"]'}),
            ) as mock_gamma,
        ):
            mock_clob.side_effect = httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
            poll_job.global_poll(db)

        mock_gamma.assert_called_once_with("m1")
        assert positions.get_position("m1", "yes") is None
        assert wallet.get_cash() == pytest.approx(cash_before + 10.0)

    def test_404_without_position_skips_gamma(self, db, services):
        """No positions on the closed market → zero Gamma requests."""
        wallet, positions, resolver = services
        _seed(db)
        poll_job.init_poller(
            db=db, wallet=wallet, positions=positions, resolver=resolver,
        )

        with (
            patch("scanner.core.clob.fetch_clob_market_data") as mock_clob,
            patch.object(poll_job, "_fetch_gamma_market", new=AsyncMock()) as mock_gamma,
        ):
            mock_clob.side_effect = httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
            poll_job.global_poll(db)

        mock_gamma.assert_not_called()

    def test_no_closed_markets_this_tick_skips_resolution_pass(self, db, services):
        """Normal tick with all markets returning 200 → zero Gamma requests."""
        wallet, positions, resolver = services
        _seed(db)
        poll_job.init_poller(
            db=db, wallet=wallet, positions=positions, resolver=resolver,
        )

        with (
            patch("scanner.core.clob.fetch_clob_market_data") as mock_clob,
            patch.object(poll_job, "_fetch_gamma_market", new=AsyncMock()) as mock_gamma,
        ):
            mock_clob.return_value = {
                "yes_price": 0.55, "no_price": 0.45,
                "best_bid": 0.54, "best_ask": 0.56, "spread": 0.02,
                "last_trade_price": 0.55, "bid_depth": 800.0, "ask_depth": 600.0,
                "book_bids": "[]", "book_asks": "[]", "recent_trades": "[]",
            }
            poll_job.global_poll(db)

        mock_gamma.assert_not_called()

    def test_gamma_timeout_does_not_crash_poll(self, db, services):
        """A Gamma timeout must not propagate and halt the poll."""
        wallet, positions, resolver = services
        _seed(db)
        positions.add_shares(
            market_id="m1", side="yes", event_id="e1", title="Q",
            shares=10, price=0.5,
        )
        poll_job.init_poller(
            db=db, wallet=wallet, positions=positions, resolver=resolver,
        )

        with (
            patch("scanner.core.clob.fetch_clob_market_data") as mock_clob,
            patch.object(
                poll_job, "_fetch_gamma_market", new=AsyncMock(return_value=None),
            ),
        ):
            mock_clob.side_effect = httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
            # Must not raise.
            poll_job.global_poll(db)

        # Position and cash preserved — next tick will retry resolution.
        assert positions.get_position("m1", "yes") is not None
