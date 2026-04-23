"""Tests for scoring.py v2 changes: weight totals, verifiability layers,
net_edge bid_depth guard, and extended time_structure range."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from polily.core.models import BookLevel, Market
from polily.scan.scoring import (
    _DEFAULT_WEIGHTS,
    _TYPE_WEIGHTS,
    _score_net_edge,
    _score_objective_verifiability,
    _score_time_structure,
)
from tests.conftest import make_market

# ---------------------------------------------------------------------------
# Weight totals must equal 100
# ---------------------------------------------------------------------------

class TestWeightTotals:
    def test_crypto_weights_sum_100(self):
        assert sum(_TYPE_WEIGHTS["crypto"].values()) == 100

    def test_sports_weights_sum_100(self):
        assert sum(_TYPE_WEIGHTS["sports"].values()) == 100

    def test_political_weights_sum_100(self):
        assert sum(_TYPE_WEIGHTS["political"].values()) == 100

    def test_default_weights_sum_100(self):
        assert sum(_DEFAULT_WEIGHTS.values()) == 100


# ---------------------------------------------------------------------------
# Objective Verifiability — Layer 1 (resolution type classification)
# ---------------------------------------------------------------------------

class TestObjectiveVerifiabilityLayer1:
    def test_numeric_threshold_high_score(self):
        """Market with 'BTC above $72,000' should hit numeric threshold (0.50)."""
        m = make_market(
            title="Will BTC be above $72,000 by June?",
            description="Resolves based on Binance spot price.",
            resolution_source="https://www.binance.com/en/trade/BTC_USDT",
        )
        score = _score_objective_verifiability(m)
        # Numeric threshold (0.50) + API-grade source → high
        assert score >= 0.8

    def test_numeric_count_high_score(self):
        """Market with '# tweets' should classify as numeric count."""
        m = make_market(
            title="Will Elon post # tweets above 100 this week?",
            description="Count of tweets from @elonmusk account.",
            resolution_source=None,
        )
        score = _score_objective_verifiability(m)
        # Numeric count (0.45) + some description → decent score
        assert score >= 0.4

    def test_official_result_classification(self):
        """'Who will win election' should classify as official result."""
        m = make_market(
            title="Who will win the 2026 Senate election?",
            description="Resolves based on certified election results.",
            resolution_source="https://www.fec.gov",
        )
        score = _score_objective_verifiability(m)
        # Official result (0.40) + API-grade .gov source (0.50)
        assert score >= 0.7

    def test_official_data_boj(self):
        """Bank of Japan decision with bps/boj.or.jp → official data (high)."""
        m = make_market(
            title="Bank of Japan Decision on Interest Rate",
            description="Resolves YES if BOJ raises rate by 25 bps. Source: boj.or.jp",
            resolution_source=None,
        )
        score = _score_objective_verifiability(m)
        # Official data (0.45) + boj.or.jp in description (0.40)
        assert score >= 0.7

    def test_vague_words_lower_score(self):
        """Title with vague resolution words should reduce score."""
        m = make_market(
            title="Will the conflict end by December?",
            description="This market resolves YES if qualifying events "
                        "lead to a significant and meaningful ceasefire.",
            resolution_source=None,
        )
        score = _score_objective_verifiability(m)
        # Status judgment (0.10) * vague penalty + minimal source quality
        assert score < 0.3


# ---------------------------------------------------------------------------
# Objective Verifiability — Layer 2 (source quality)
# ---------------------------------------------------------------------------

class TestObjectiveVerifiabilityLayer2:
    def test_binance_url_high_source(self):
        """Resolution source with binance URL → API-grade (0.50)."""
        m = make_market(
            title="Will BTC be above $100,000?",
            resolution_source="https://www.binance.com/en/trade/BTC_USDT",
            description="Resolves based on Binance spot price at expiry.",
        )
        score = _score_objective_verifiability(m)
        # Numeric threshold (0.50) + API-grade Binance (0.50) → capped at 1.0
        assert score >= 0.9

    def test_boj_in_description_high(self):
        """boj.or.jp mentioned in description → API-grade in description (0.40)."""
        m = make_market(
            title="BOJ interest rate decision March",
            description="Source: https://www.boj.or.jp for official rate announcement. "
                        "Resolves YES if rate is raised by 25 bps.",
            resolution_source=None,
        )
        score = _score_objective_verifiability(m)
        assert score >= 0.6

    def test_no_description_low_source(self):
        """Market with no description/rules/source → minimal Layer 2."""
        m = make_market(
            title="Will something happen?",
            description=None,
            rules=None,
            resolution_source=None,
        )
        score = _score_objective_verifiability(m)
        # Status judgment default (0.10) + no source (0.00)
        assert score <= 0.15


# ---------------------------------------------------------------------------
# Net Edge — bid_depth guard
# ---------------------------------------------------------------------------

class TestNetEdgeBidDepth:
    def test_no_bid_depth_returns_zero(self):
        """Market with no total_bid_depth_usd should return 0 even with deviation."""
        m = make_market(
            book_depth_bids=None,
            book_depth_asks=[BookLevel(price=0.56, size=500)],
        )
        mispricing = SimpleNamespace(deviation_pct=0.08)
        assert _score_net_edge(m, mispricing) == 0.0

    def test_with_bid_depth_and_deviation(self):
        """Market with bid depth and deviation should score > 0."""
        m = make_market(
            best_bid_yes=0.545,
            best_ask_yes=0.555,
            book_depth_bids=[BookLevel(price=0.54, size=2000), BookLevel(price=0.53, size=3000)],
            book_depth_asks=[BookLevel(price=0.56, size=2000)],
        )
        mispricing = SimpleNamespace(deviation_pct=0.08)
        score = _score_net_edge(m, mispricing)
        assert score > 0.0

    def test_no_deviation_returns_zero(self):
        """No mispricing deviation → 0."""
        m = make_market()
        mispricing = SimpleNamespace(deviation_pct=0)
        assert _score_net_edge(m, mispricing) == 0.0


# ---------------------------------------------------------------------------
# Time Structure — extended range (14-30 days)
# ---------------------------------------------------------------------------

def _market_with_days(days: float) -> "Market":
    """Helper: create a market with exact days_to_resolution."""
    base = datetime(2026, 4, 1, tzinfo=UTC)
    return make_market(
        data_fetched_at=base,
        resolution_time=base + timedelta(days=days),
    )


class TestTimeStructureExtended:
    def test_3_days_sweet_spot(self):
        """3 days is in [1,5] sweet spot → should be high."""
        m = _market_with_days(3)
        score = _score_time_structure(m)
        assert score >= 0.7

    def test_16_days_nonzero(self):
        """16 days should produce > 0 (was 0 before fix)."""
        m = _market_with_days(16)
        score = _score_time_structure(m)
        assert score > 0

    def test_25_days_nonzero(self):
        """25 days should produce > 0."""
        m = _market_with_days(25)
        score = _score_time_structure(m)
        assert score > 0

    def test_31_days_zero(self):
        """31 days is past the 30-day cutoff → 0."""
        m = _market_with_days(31)
        score = _score_time_structure(m)
        assert score == 0.0

    def test_monotonic_decay(self):
        """Score should decrease as days increase past sweet spot."""
        s3 = _score_time_structure(_market_with_days(3))
        s10 = _score_time_structure(_market_with_days(10))
        s20 = _score_time_structure(_market_with_days(20))
        s28 = _score_time_structure(_market_with_days(28))
        assert s3 > s10 > s20 > s28 > 0
