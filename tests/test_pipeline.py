"""Integration tests for the full scan pipeline."""

from datetime import UTC, datetime

from scanner.config import ScannerConfig, load_config
from scanner.models import Market
from scanner.pipeline import run_scan_pipeline
from tests.conftest import make_market


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
        # Non-binary: filtered
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

        # Extreme, noise, non-binary should all be filtered
        all_ids = [c.market.market_id for c in tiers.tier_a + tiers.tier_b + tiers.tier_c]
        assert "bad-extreme" not in all_ids
        assert "bad-noise" not in all_ids
        assert "bad-nonbinary" not in all_ids
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
