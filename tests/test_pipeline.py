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
            resolution_time=datetime(2026, 4, 20, tzinfo=UTC),
        ),
        # Good economics market
        make_market(
            market_id="good-econ",
            title="Will CPI exceed 3.5% in March?",
            yes_price=0.55,
            volume=60000,
            open_interest=40000,
            resolution_source="https://bls.gov",
            resolution_time=datetime(2026, 4, 25, tzinfo=UTC),
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
    def test_pipeline_does_not_crash(self):
        """Pipeline should not crash with various market types."""
        config = load_config(
            __import__("pathlib").Path("config.example.yaml"),
        )
        config.ai.enabled = False

        markets = _sample_markets()
        event_rows = [make_event(event_id="ev_test", volume=500000)]
        tiers = run_scan_pipeline(markets, config, event_rows=event_rows)
        assert tiers is not None
        # All are in same event (ev_test), so all pass if event passes

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
    """Pipeline persists ONLY filtered events to DB, scores ALL their sub-markets."""

    def test_only_filtered_events_in_db(self, tmp_path):
        """DB should only contain events that pass event-level filter."""
        db = PolilyDB(tmp_path / "test.db")

        event_rows = [
            make_event(event_id="ev1", volume=500000),   # good quality → passes both stages
            make_event(event_id="ev2", volume=100),      # low volume → rejected at stage 1
        ]
        markets = [
            make_market(
                market_id="m1", event_id="ev1",
                title="Will BTC be above $88,000 on March 30?",
                yes_price=0.50, volume=80000, open_interest=50000,
                resolution_source="https://coingecko.com",
                resolution_time=datetime(2026, 4, 20, tzinfo=UTC),
            ),
            make_market(
                market_id="m2", event_id="ev2",
                title="Low volume event",
                yes_price=0.50, volume=500, open_interest=100,
                resolution_time=datetime(2026, 4, 20, tzinfo=UTC),
            ),
        ]

        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        run_scan_pipeline(markets, config, db=db, event_rows=event_rows)

        # ev1 should be in DB (good volume)
        ev1 = get_event("ev1", db)
        assert ev1 is not None
        assert ev1.structure_score is not None

        # ev2 should NOT be in DB (low volume)
        ev2 = get_event("ev2", db)
        assert ev2 is None
        db.close()

    def test_multi_outcome_all_siblings_scored(self, tmp_path):
        """All sub-markets of a passing event are scored — including low-probability ones."""
        db = PolilyDB(tmp_path / "test.db")

        event_rows = [make_event(event_id="ev1", market_count=3, volume=500000)]
        markets = [
            # Realistic multi-outcome: probabilities sum near 1.0
            make_market(
                market_id="m1", event_id="ev1",
                title="Team A wins?",
                yes_price=0.50, volume=200000, open_interest=100000,
                resolution_time=datetime(2026, 4, 20, tzinfo=UTC),
                clob_token_id_yes="tok1",
            ),
            make_market(
                market_id="m2", event_id="ev1",
                title="Draw?",
                yes_price=0.25, volume=80000, open_interest=50000,
                resolution_time=datetime(2026, 4, 20, tzinfo=UTC),
                clob_token_id_yes="tok2",
            ),
            make_market(
                market_id="m3", event_id="ev1",
                title="Team B wins?",
                yes_price=0.25, volume=80000, open_interest=50000,
                resolution_time=datetime(2026, 4, 20, tzinfo=UTC),
                clob_token_id_yes="tok3",
            ),
        ]

        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        # Mock enrich_with_orderbook to simulate CLOB book fetch for ALL markets
        from unittest.mock import patch

        from scanner.core.models import BookLevel
        async def mock_enrich(mkts, cfg):
            for m in mkts:
                if m.clob_token_id_yes:
                    m.book_depth_bids = [BookLevel(price=0.5, size=1000)]
                    m.book_depth_asks = [BookLevel(price=0.6, size=800)]
            return mkts

        with patch("scanner.scan.pipeline.enrich_with_orderbook", mock_enrich):
            run_scan_pipeline(markets, config, db=db, event_rows=event_rows)

        # ALL 3 markets should be in DB (siblings of passing event)
        m1 = get_market("m1", db)
        m2 = get_market("m2", db)
        m3 = get_market("m3", db)
        assert m1 is not None
        assert m2 is not None
        assert m3 is not None

        # ALL siblings should have structure_score (event-level filter → all scored)
        assert m1.structure_score is not None
        assert m2.structure_score is not None  # extreme price but still scored
        assert m3.structure_score is not None  # extreme price but still scored

        # ALL siblings should have score_breakdown
        assert m1.score_breakdown is not None
        assert m2.score_breakdown is not None
        assert m3.score_breakdown is not None

        # Event should have event-level quality score (NOT max of sub-markets)
        ev = get_event("ev1", db)
        assert ev is not None
        assert ev.structure_score is not None
        assert ev.structure_score > 0  # event-level score, different from sub-market scores
        db.close()

    def test_pipeline_updates_event_scores(self, tmp_path):
        """Events get structure_score and tier after pipeline."""
        db = PolilyDB(tmp_path / "test.db")

        event_rows = [make_event(event_id="ev1", volume=500000)]
        markets = [
            make_market(
                market_id="m1", event_id="ev1",
                title="Will BTC be above $88,000 on March 30?",
                yes_price=0.50, volume=80000, open_interest=50000,
                resolution_source="https://coingecko.com",
                resolution_time=datetime(2026, 4, 20, tzinfo=UTC),
            ),
        ]
        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        run_scan_pipeline(markets, config, db=db, event_rows=event_rows)

        event = get_event("ev1", db)
        assert event is not None
        assert event.structure_score > 0
        assert event.tier == "research"  # all quality-gated events are research
        db.close()

    def test_pipeline_without_db_still_works(self):
        """Pipeline without db= should not crash."""
        config = load_config(__import__("pathlib").Path("config.example.yaml"))
        config.ai.enabled = False

        markets = _sample_markets()
        # Without event_rows, synthetic events are created. Some may not pass
        # the quality gate, but pipeline should not crash.
        tiers = run_scan_pipeline(markets, config)
        # Just verify it returns a valid TierResult
        assert tiers is not None
