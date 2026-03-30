"""Shared test fixtures and factory functions."""

import json
from datetime import UTC, datetime

from scanner.models import BookLevel, Market


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
    """Simulate claude CLI JSON output for agent tests.

    Matches actual claude CLI format: {"type":"result", "result":"```json\n{...}\n```"}
    """
    json_text = json.dumps(structured_output)
    return json.dumps({
        "type": "result",
        "result": f"```json\n{json_text}\n```",
        "session_id": "test-session",
    }).encode()
