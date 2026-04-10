"""Shared test fixtures and factory functions."""

import json
from datetime import UTC, datetime

import pytest

from scanner.core.db import PolilyDB
from scanner.core.models import BookLevel, Market


@pytest.fixture(autouse=True)
def _suppress_desktop_notifications(monkeypatch):
    """Globally prevent real macOS notifications during all tests."""
    monkeypatch.setattr("scanner.notifications.subprocess.run", lambda *a, **kw: None)


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
