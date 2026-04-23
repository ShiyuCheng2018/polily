"""Shared test fixtures and factory functions."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from polily.core.models import BookLevel, Market


@pytest.fixture(autouse=True)
def _suppress_agent_debug_log(monkeypatch):
    """Prevent tests from writing agent_debug.log to data/."""
    monkeypatch.setattr("polily.agents.base._dump_debug", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def _isolate_poll_log(monkeypatch):
    """Prevent tests from polluting prod data/poll.log + leaking tick state.

    `polily.daemon.poll_job` owns two module-level singletons:
      - `_poll_log` — a FileHandler-backed logger hard-coded to
        `<project_root>/data/poll.log`
      - `_poll_count` — monotonic tick counter

    Without this fixture, every integration test that exercises
    `global_poll()` or `_resolve_closed_market_if_position()` appends to
    the developer's live log and carries tick numbers across tests.
    Tests that need to assert on log content override this by calling
    `patch.object(poll_job, '_get_poll_log', return_value=...)` within
    the test body — patch.object stacks on top of monkeypatch.
    """
    from polily.daemon import poll_job
    poll_job._poll_log = None
    poll_job._poll_count = 0
    monkeypatch.setattr(poll_job, "_get_poll_log", lambda: MagicMock())
    yield
    poll_job._poll_log = None
    poll_job._poll_count = 0


@pytest.fixture
def polily_db(tmp_path):
    """Provide a PolilyDB in a temp directory that auto-cleans up."""
    db = PolilyDB(tmp_path / "polily.db")
    yield db
    db.close()


def make_market(**overrides) -> Market:
    """Factory for creating Market instances with sensible defaults."""
    defaults = dict(
        market_id="0xtest",
        event_id="ev_test",
        title="Will BTC be above $88,000 on March 30?",
        outcomes=["Yes", "No"],
        yes_price=0.55,
        no_price=0.47,
        best_bid_yes=0.54,
        best_ask_yes=0.56,
        spread_yes=0.02,
        volume=50000.0,
        open_interest=30000.0,
        resolution_time=datetime(2026, 3, 30, tzinfo=UTC),
        data_fetched_at=datetime(2026, 3, 28, 0, 0, tzinfo=UTC),
        book_depth_bids=[BookLevel(price=0.54, size=500), BookLevel(price=0.53, size=800)],
        book_depth_asks=[BookLevel(price=0.56, size=400), BookLevel(price=0.57, size=600)],
    )
    defaults.update(overrides)
    return Market(**defaults)


def make_cli_response(structured_output: dict) -> bytes:
    """Simulate claude CLI JSON output (v2.1+ array format without --json-schema).

    Matches format: [{"type":"system",...}, {"type":"result","result":"```json\n{...}\n```"}]
    """
    json_text = json.dumps(structured_output)
    return json.dumps([
        {"type": "system", "subtype": "init", "cwd": "/test", "session_id": "test-session"},
        {
            "type": "result",
            "subtype": "success",
            "result": f"```json\n{json_text}\n```",
            "session_id": "test-session",
        },
    ]).encode()


def make_event(**overrides) -> EventRow:
    """Factory for creating EventRow instances with sensible defaults."""
    defaults = dict(
        event_id="ev_test",
        title="Test Event",
        slug="test-event",
        description="This market will resolve to Yes if the condition is met based on official data from the relevant authority.",
        resolution_source="https://official-source.com",
        volume=200000,
        neg_risk=False,
        market_count=1,
        active=1,
        closed=0,
        updated_at="2026-04-10T00:00:00",
    )
    defaults.update(overrides)
    return EventRow(**defaults)


def setup_event_and_market(db, event_id="ev1", market_id="m1", **market_overrides):
    """Create an event + market in DB for testing."""
    upsert_event(make_event(event_id=event_id), db)
    defaults = dict(
        market_id=market_id,
        event_id=event_id,
        question="Test market question",
        updated_at="2026-04-10T00:00:00",
    )
    defaults.update(market_overrides)
    upsert_market(MarketRow(**defaults), db)


def make_cli_response_structured(structured_output: dict) -> bytes:
    """Simulate claude CLI JSON output (v2.1+ array format with --json-schema).

    When --json-schema is used, response comes in structured_output, not result.
    """
    return json.dumps([
        {"type": "system", "subtype": "init", "cwd": "/test", "session_id": "test-session"},
        {
            "type": "result",
            "subtype": "success",
            "result": "",
            "structured_output": structured_output,
            "session_id": "test-session",
        },
    ]).encode()
