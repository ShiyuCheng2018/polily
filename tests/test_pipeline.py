"""Integration tests for the full scan pipeline."""

from datetime import UTC, datetime

from scanner.core.config import ScannerConfig, load_config
from scanner.core.db import PolilyDB
from scanner.core.event_store import get_event, get_market
from scanner.core.models import Market
from scanner.scan.pipeline import run_scan_pipeline
from tests.conftest import make_event, make_market


def _sample_markets() -> list[Market]:
    """Create a diverse set of markets for pipeline testing."""
    return [
        # Good crypto market — should pass filters, get scored
        make_market(
            market_id="good-crypto",
            title="Will BTC be above $88,000 on March 30?",
            yes_price=0.50,
            volume=80000,
            open_interest=50000,
            resolution_source="https://coingecko.com",
            resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
        ),
        # Good economics market
        make_market(
            market_id="good-econ",
            title="Will CPI exceed 3.5% in March?",
            yes_price=0.55,
            volume=60000,
            open_interest=40000,
            resolution_source="https://bls.gov",
            resolution_time=datetime(2026, 4, 2, tzinfo=UTC),
        ),
        # Should be filtered: extreme probability
        make_market(
            market_id="bad-extreme",
            title="Will sun rise tomorrow?",
            yes_price=0.95,
            volume=50000,
        ),
        # Should be filtered: no volume
        make_market(
            market_id="bad-volume",
            title="Will something happen?",
            yes_price=0.50,
            volume=100,
            open_interest=50,
        ),
        # Should be filtered: noise market
        make_market(
            market_id="bad-noise",
            title="BTC 5 min up or down?",
            yes_price=0.50,
            volume=50000,
        ),
        # Non-binary: v0.5.0 now passes through (multi-outcome support)
        make_market(
            market_id="bad-nonbinary",
            title="Who wins?",
            outcomes=["A", "B", "C"],
            yes_price=0.33,
            volume=50000,
        ),
    ]


class TestRunPipelineNoAI:
    def test_pipeline_filters_and_scores(self):
        config = load_config(
            __import__("pathlib").Path("config.example.yaml"),
        )
        # Disable AI for this test
        config.ai.enabled = False

        markets = _sample_markets()
        tiers = run_scan_pipeline(markets, config)

        # good-crypto and good-econ should pass; others filtered
        total_scored = len(tiers.tier_a) + len(tiers.tier_b) + len(tiers.tier_c)
        assert total_scored >= 1  # at least good-econ should pass

        # Extreme, noise should be filtered; non-binary now passes (v0.5.0)
        all_ids = [c.market.market_id for c in tiers.tier_a + tiers.tier_b + tiers.tier_c]
        assert "bad-extreme" not in all_ids
        assert "bad-noise" not in all_ids
        # v0.5.0: multi-outcome markets now pass through
        assert "bad-nonbinary" in all_ids
        assert "bad-volume" not in all_ids

    def test_pipeline_assigns_market_type(self):
        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        markets = _sample_markets()
        tiers = run_scan_pipeline(markets, config)

        all_candidates = tiers.tier_a + tiers.tier_b + tiers.tier_c
        for c in all_candidates:
            assert c.market.market_type is not None

    def test_pipeline_scores_are_bounded(self):
        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        markets = _sample_markets()
        tiers = run_scan_pipeline(markets, config)

        for c in tiers.tier_a + tiers.tier_b + tiers.tier_c:
            assert 0 <= c.score.total <= 100

    def test_pipeline_with_empty_input(self):
        config = ScannerConfig()
        tiers = run_scan_pipeline([], config)
        assert len(tiers.tier_a) == 0
        assert len(tiers.tier_b) == 0
        assert len(tiers.tier_c) == 0


class TestRunPipelineAIDisabled:
    """Pipeline with AI disabled should work identically to rule-based mode."""

    def test_ai_disabled_same_as_no_ai(self):
        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        markets = _sample_markets()
        tiers = run_scan_pipeline(markets, config)

        # Should still produce valid results
        for c in tiers.tier_a + tiers.tier_b + tiers.tier_c:
            assert c.score.total >= 0
            assert c.market.market_type is not None


class TestPipelineDBPersistence:
    """Pipeline persists ONLY filtered events+markets to DB, then scores them."""

    def test_only_filtered_events_in_db(self, tmp_path):
        """DB should only contain events whose markets passed filter."""
        db = PolilyDB(tmp_path / "test.db")

        # Two event_rows: ev1 has a good market, ev2 has a bad market
        event_rows = [
            make_event(event_id="ev1"),
            make_event(event_id="ev2"),
        ]
        markets = [
            # ev1: good market (passes filter)
            make_market(
                market_id="m1", event_id="ev1",
                title="Will BTC be above $88,000 on March 30?",
                yes_price=0.50, volume=80000, open_interest=50000,
                resolution_source="https://coingecko.com",
                resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
            ),
            # ev2: bad market (extreme price, will be filtered)
            make_market(
                market_id="m2", event_id="ev2",
                title="Bad extreme",
                yes_price=0.98, volume=500, open_interest=100,
                resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
            ),
        ]

        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        run_scan_pipeline(markets, config, db=db, event_rows=event_rows)

        # ev1 should be in DB (had passing market)
        ev1 = get_event("ev1", db)
        assert ev1 is not None
        assert ev1.structure_score is not None

        # ev2 should NOT be in DB (no passing market)
        ev2 = get_event("ev2", db)
        assert ev2 is None

        # Only m1 should be in DB
        m1 = get_market("m1", db)
        assert m1 is not None
        m2 = get_market("m2", db)
        assert m2 is None
        db.close()

    def test_multi_outcome_event_all_siblings_persisted(self, tmp_path):
        """If one sub-market passes, ALL sibling markets of that event are persisted."""
        db = PolilyDB(tmp_path / "test.db")

        event_rows = [make_event(event_id="ev1", market_count=3)]
        markets = [
            # m1: passes filter (good price, volume)
            make_market(
                market_id="m1", event_id="ev1",
                title="Will BTC be above $88,000?",
                yes_price=0.50, volume=80000, open_interest=50000,
                resolution_source="https://coingecko.com",
                resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
            ),
            # m2: would fail filter on its own (extreme price)
            make_market(
                market_id="m2", event_id="ev1",
                title="Will BTC be above $90,000?",
                yes_price=0.05, volume=80000, open_interest=50000,
                resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
            ),
            # m3: would fail filter on its own (extreme price)
            make_market(
                market_id="m3", event_id="ev1",
                title="Will BTC be above $95,000?",
                yes_price=0.02, volume=80000, open_interest=50000,
                resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
            ),
        ]

        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        run_scan_pipeline(markets, config, db=db, event_rows=event_rows)

        # ALL 3 markets should be in DB (siblings of passing event)
        assert get_market("m1", db) is not None
        assert get_market("m2", db) is not None
        assert get_market("m3", db) is not None

        # Event should be in DB with score
        ev = get_event("ev1", db)
        assert ev is not None
        assert ev.structure_score is not None
        db.close()

    def test_pipeline_updates_event_scores(self, tmp_path):
        """Events get structure_score and tier after pipeline."""
        db = PolilyDB(tmp_path / "test.db")

        event_rows = [make_event(event_id="ev1")]
        markets = [
            make_market(
                market_id="m1", event_id="ev1",
                title="Will BTC be above $88,000 on March 30?",
                yes_price=0.50, volume=80000, open_interest=50000,
                resolution_source="https://coingecko.com",
                resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
            ),
        ]
        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        run_scan_pipeline(markets, config, db=db, event_rows=event_rows)

        event = get_event("ev1", db)
        assert event is not None
        assert event.structure_score > 0
        assert event.tier in ("research", "watchlist", "filtered")
        db.close()

    def test_pipeline_without_db_still_works(self):
        """Pipeline without db= should work as before (no DB writes)."""
        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        markets = _sample_markets()
        tiers = run_scan_pipeline(markets, config)
        total_scored = len(tiers.tier_a) + len(tiers.tier_b) + len(tiers.tier_c)
        assert total_scored >= 1
