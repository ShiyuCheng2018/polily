"""OBS-1: per-market fetch retries 3x on transient errors, but a
circuit breaker aborts further retries this tick after 5 consecutive
ConnectErrors. Prevents the 19-minute worst-case retry storm during
sustained outages.
"""
from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_fetch_one_retries_3x_on_transient_error(monkeypatch):
    """Single transient ConnectError -> tenacity retries -> succeeds on
    2nd attempt -> no exception raised."""
    from polily.daemon import poll_job

    call_count = {"n": 0}

    async def _flaky_fetch(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise httpx.ConnectError("simulated transient")
        return {"price": 0.5}  # success on 2nd attempt

    monkeypatch.setattr(poll_job, "fetch_clob_market_data", _flaky_fetch)
    poll_job._reset_tick_circuit_breaker()

    market = type("M", (), {"clob_token_id_yes": "test_token"})()
    async with httpx.AsyncClient(timeout=10) as client:
        result = await poll_job._fetch_one(client, market)

    assert result == {"price": 0.5}
    assert call_count["n"] == 2  # one retry, then success


@pytest.mark.asyncio
async def test_fetch_one_gives_up_after_3_attempts(monkeypatch):
    """Persistent failure -> tenacity exhausts after 3 -> re-raises."""
    from polily.daemon import poll_job

    call_count = {"n": 0}

    async def _always_fail(*args, **kwargs):
        call_count["n"] += 1
        raise httpx.ConnectError("persistent")

    monkeypatch.setattr(poll_job, "fetch_clob_market_data", _always_fail)
    poll_job._reset_tick_circuit_breaker()

    market = type("M", (), {"clob_token_id_yes": "test_token"})()
    async with httpx.AsyncClient(timeout=10) as client:
        with pytest.raises(httpx.ConnectError):
            await poll_job._fetch_one(client, market)

    assert call_count["n"] == 3  # 3 attempts total, then re-raise


@pytest.mark.asyncio
async def test_circuit_breaker_skips_retries_after_5_failures(monkeypatch):
    """Sustained outage: first 5 markets ConnectError. After breaker
    trips, subsequent fetches in this tick skip retries (1 attempt only)."""
    from polily.daemon import poll_job

    call_count = {"n": 0}

    async def _always_fail(*args, **kwargs):
        call_count["n"] += 1
        raise httpx.ConnectError("outage")

    monkeypatch.setattr(poll_job, "fetch_clob_market_data", _always_fail)

    # Reset breaker state for this tick
    poll_job._reset_tick_circuit_breaker()

    market = type("M", (), {"clob_token_id_yes": "x"})()
    async with httpx.AsyncClient(timeout=10) as client:
        # First 5 markets: each hits 3 retries = 15 attempts
        for _ in range(5):
            with pytest.raises(httpx.ConnectError):
                await poll_job._fetch_one(client, market)

        # 6th market: breaker tripped, only 1 attempt
        breaker_count_before = call_count["n"]
        with pytest.raises(httpx.ConnectError):
            await poll_job._fetch_one(client, market)
        new_attempts = call_count["n"] - breaker_count_before

    assert new_attempts == 1, (
        f"Circuit breaker should limit to 1 attempt after 5 consecutive "
        f"failures; got {new_attempts}"
    )
