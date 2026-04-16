"""Tests for MovementSparkline component logic."""

from datetime import UTC, datetime, timedelta

from scanner.tui.components.movement_sparkline import get_event_movement


def _make_entry(minutes_ago: int = 0, market_id: str = "m1",
                magnitude: float = 0, quality: float = 0,
                label: str = "noise"):
    ts = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "market_id": market_id,
        "created_at": ts,
        "magnitude": magnitude,
        "quality": quality,
        "label": label,
    }


class TestGetEventMovement:
    def test_empty(self):
        m, q, label = get_event_movement([])
        assert m == 0
        assert q == 0
        assert label == "noise"

    def test_noise_only(self):
        entries = [_make_entry(magnitude=5, quality=2)]
        m, q, label = get_event_movement(entries)
        assert m == 5
        assert q == 2
        assert label == "noise"

    def test_takes_max_across_markets(self):
        entries = [
            _make_entry(market_id="m1", magnitude=30, quality=20, label="noise"),
            _make_entry(market_id="m2", magnitude=60, quality=50, label="whale_move"),
        ]
        m, q, label = get_event_movement(entries)
        assert m == 60
        assert q == 50
        assert label == "whale_move"

    def test_consensus(self):
        entries = [_make_entry(magnitude=80, quality=70, label="consensus")]
        m, q, label = get_event_movement(entries)
        assert label == "consensus"

    def test_skips_event_level(self):
        entries = [
            {"market_id": None, "created_at": datetime.now(UTC).isoformat(),
             "magnitude": 90, "quality": 80, "label": "consensus"},
        ]
        m, q, label = get_event_movement(entries)
        assert label == "noise"  # event-level skipped
