"""Integration tests for the full scan pipeline."""

from datetime import UTC, datetime

from scanner.core.config import ScannerConfig, load_config
from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, get_event, get_market, upsert_event, upsert_market
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
    """Pipeline updates event scores and market scores in DB when db= is passed."""

    def test_pipeline_updates_event_scores_in_db(self, tmp_path):
        """After pipeline runs, events.structure_score and events.tier should be set."""
        db = PolilyDB(tmp_path / "test.db")

        # Pre-seed event + market in DB (simulating what service does before pipeline)
        ev = make_event(event_id="ev1")
        upsert_event(ev, db)
        upsert_market(MarketRow(
            market_id="good-crypto",
            event_id="ev1",
            question="Will BTC be above $88,000 on March 30?",
            updated_at="2026-04-10T00:00:00",
        ), db)

        market = make_market(
            market_id="good-crypto",
            event_id="ev1",
            title="Will BTC be above $88,000 on March 30?",
            yes_price=0.50,
            volume=80000,
            open_interest=50000,
            resolution_source="https://coingecko.com",
            resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
        )
        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        tiers = run_scan_pipeline([market], config, db=db)

        # Event should have structure_score and tier set
        event = get_event("ev1", db)
        assert event is not None
        assert event.structure_score is not None
        assert event.structure_score > 0
        assert event.tier in ("research", "watchlist", "filtered")

        # Market should also have structure_score set
        mkt = get_market("good-crypto", db)
        assert mkt is not None
        assert mkt.structure_score is not None
        assert mkt.structure_score > 0
        db.close()

    def test_pipeline_without_db_still_works(self):
        """Pipeline without db= should work as before (no DB writes)."""
        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        markets = _sample_markets()
        # No db argument — should not raise
        tiers = run_scan_pipeline(markets, config)
        total_scored = len(tiers.tier_a) + len(tiers.tier_b) + len(tiers.tier_c)
        assert total_scored >= 1

    def test_pipeline_updates_multiple_events(self, tmp_path):
        """Multiple events with markets get their scores updated."""
        db = PolilyDB(tmp_path / "test.db")

        # Seed two events
        upsert_event(make_event(event_id="ev1"), db)
        upsert_event(make_event(event_id="ev2"), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1",
            question="Q1", updated_at="now",
        ), db)
        upsert_market(MarketRow(
            market_id="m2", event_id="ev2",
            question="Q2", updated_at="now",
        ), db)

        markets = [
            make_market(
                market_id="m1", event_id="ev1",
                title="Will BTC be above $88,000 on March 30?",
                yes_price=0.50, volume=80000, open_interest=50000,
                resolution_source="https://coingecko.com",
                resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
            ),
            make_market(
                market_id="m2", event_id="ev2",
                title="Will CPI exceed 3.5% in March?",
                yes_price=0.55, volume=60000, open_interest=40000,
                resolution_source="https://bls.gov",
                resolution_time=datetime(2026, 4, 2, tzinfo=UTC),
            ),
        ]

        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        run_scan_pipeline(markets, config, db=db)

        # Both events should have scores
        ev1 = get_event("ev1", db)
        ev2 = get_event("ev2", db)
        assert ev1 is not None and ev1.structure_score is not None
        assert ev2 is not None and ev2.structure_score is not None
        assert ev1.tier is not None
        assert ev2.tier is not None
        db.close()

    def test_pipeline_event_gets_max_market_score(self, tmp_path):
        """When event has multiple markets, event.structure_score = max(market scores)."""
        db = PolilyDB(tmp_path / "test.db")

        # Single event with two markets
        upsert_event(make_event(event_id="ev1"), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1",
            question="Q1", updated_at="now",
        ), db)
        upsert_market(MarketRow(
            market_id="m2", event_id="ev1",
            question="Q2", updated_at="now",
        ), db)

        markets = [
            make_market(
                market_id="m1", event_id="ev1",
                title="Will BTC be above $88,000 on March 30?",
                yes_price=0.50, volume=80000, open_interest=50000,
                resolution_source="https://coingecko.com",
                resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
            ),
            make_market(
                market_id="m2", event_id="ev1",
                title="Will BTC be above $90,000 on March 30?",
                yes_price=0.55, volume=60000, open_interest=40000,
                resolution_source="https://coingecko.com",
                resolution_time=datetime(2026, 4, 2, tzinfo=UTC),
            ),
        ]

        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        run_scan_pipeline(markets, config, db=db)

        ev = get_event("ev1", db)
        m1 = get_market("m1", db)
        m2 = get_market("m2", db)

        # Event score should be max of market scores
        assert ev is not None and m1 is not None and m2 is not None
        assert ev.structure_score == max(m1.structure_score, m2.structure_score)
        db.close()
