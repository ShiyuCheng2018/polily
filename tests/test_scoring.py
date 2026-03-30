"""Tests for market type classifier and beauty score."""

from datetime import UTC, datetime

from scanner.config import FiltersConfig, MarketTypeConfig, ScoringWeights
from scanner.market_classifier import classify_market_type
from scanner.models import BookLevel
from scanner.scoring import compute_beauty_score, normalize_weights
from tests.conftest import make_market

# --- Market Type Classifier ---

class TestClassifyMarketType:
    def _types_config(self) -> dict[str, MarketTypeConfig]:
        return {
            "crypto_threshold": MarketTypeConfig(
                keywords=["btc", "eth", "bitcoin", "ethereum", "above", "below", "price"],
                mispricing_enabled=True,
            ),
            "political": MarketTypeConfig(
                keywords=["election", "president", "governor", "senate", "vote", "nominee"],
            ),
            "economic_data": MarketTypeConfig(
                keywords=["cpi", "inflation", "rate cut", "fomc", "jobs", "gdp", "nonfarm"],
            ),
            "sports": MarketTypeConfig(
                keywords=["game", "match", "championship", "playoff", "super bowl"],
            ),
            "tech": MarketTypeConfig(
                keywords=["ai", "openai", "nvidia", "model", "launch", "release"],
            ),
        }

    def test_crypto_market(self):
        m = make_market(title="Will BTC be above $88,000 on March 30?")
        assert classify_market_type(m, self._types_config()) == "crypto_threshold"

    def test_political_market(self):
        m = make_market(title="Will Trump win the 2026 presidential election?")
        assert classify_market_type(m, self._types_config()) == "political"

    def test_economic_market(self):
        m = make_market(title="Will CPI exceed 3.5% in March?")
        assert classify_market_type(m, self._types_config()) == "economic_data"

    def test_sports_market(self):
        m = make_market(title="Lakers win NBA championship 2026?")
        assert classify_market_type(m, self._types_config()) == "sports"

    def test_unknown_defaults_to_other(self):
        m = make_market(title="Will aliens land on Earth?")
        assert classify_market_type(m, self._types_config()) == "other"


# --- Weight Normalization ---

class TestNormalizeWeights:
    def test_already_100(self):
        w = ScoringWeights()  # default sums to 100
        nw = normalize_weights(w)
        assert sum(nw.values()) == 100

    def test_overrides_renormalize(self):
        w = ScoringWeights()
        overrides = {"catalyst_proxy": 2, "liquidity_depth": 22}
        nw = normalize_weights(w, overrides)
        assert abs(sum(nw.values()) - 100) < 0.01

    def test_override_values_reflected(self):
        w = ScoringWeights()
        overrides = {"catalyst_proxy": 10}
        nw = normalize_weights(w, overrides)
        # catalyst_proxy should be proportionally higher than default
        assert nw["catalyst_proxy"] > 5  # default is 5


# --- Beauty Score ---

class TestBeautyScore:
    def test_score_is_0_to_100(self):
        m = make_market()
        result = compute_beauty_score(m, ScoringWeights(), FiltersConfig())
        assert 0 <= result.total <= 100

    def test_perfect_market_scores_high(self):
        """A market with ideal properties should score > 70."""
        m = make_market(
            yes_price=0.50,
            best_bid_yes=0.495,
            best_ask_yes=0.505,
            volume=100000,
            open_interest=80000,
            resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
            data_fetched_at=datetime(2026, 3, 28, tzinfo=UTC),
            book_depth_bids=[BookLevel(price=0.49, size=2000), BookLevel(price=0.48, size=3000)],
            book_depth_asks=[BookLevel(price=0.51, size=2000), BookLevel(price=0.52, size=3000)],
        )
        result = compute_beauty_score(m, ScoringWeights(), FiltersConfig())
        assert result.total >= 70

    def test_bad_market_scores_low(self):
        """A market with poor properties should score < 40."""
        m = make_market(
            yes_price=0.18,
            best_bid_yes=0.10,
            best_ask_yes=0.26,
            volume=2000,
            resolution_time=datetime(2026, 4, 10, tzinfo=UTC),
            data_fetched_at=datetime(2026, 3, 28, tzinfo=UTC),
            book_depth_bids=[BookLevel(price=0.10, size=50)],
            book_depth_asks=[BookLevel(price=0.26, size=50)],
        )
        result = compute_beauty_score(m, ScoringWeights(), FiltersConfig())
        assert result.total < 40

    def test_breakdown_has_all_components(self):
        m = make_market()
        result = compute_beauty_score(m, ScoringWeights(), FiltersConfig())
        assert result.time_to_resolution >= 0
        assert result.objectivity >= 0
        assert result.probability_zone >= 0
        assert result.liquidity_depth >= 0
        assert result.exitability >= 0
        assert result.catalyst_proxy >= 0
        assert result.small_account_friendliness >= 0

    def test_breakdown_sums_to_total(self):
        m = make_market()
        result = compute_beauty_score(m, ScoringWeights(), FiltersConfig())
        component_sum = (
            result.time_to_resolution + result.objectivity + result.probability_zone
            + result.liquidity_depth + result.exitability + result.catalyst_proxy
            + result.small_account_friendliness
        )
        assert abs(component_sum - result.total) < 0.01

    def test_mid_probability_scores_higher(self):
        m_mid = make_market(yes_price=0.50)
        m_edge = make_market(yes_price=0.22)
        s_mid = compute_beauty_score(m_mid, ScoringWeights(), FiltersConfig())
        s_edge = compute_beauty_score(m_edge, ScoringWeights(), FiltersConfig())
        assert s_mid.probability_zone > s_edge.probability_zone

    def test_probability_flat_mode_no_penalty(self):
        m_mid = make_market(yes_price=0.50)
        m_edge = make_market(yes_price=0.75)
        s_mid = compute_beauty_score(m_mid, ScoringWeights(), FiltersConfig(), probability_penalty_mode="flat")
        s_edge = compute_beauty_score(m_edge, ScoringWeights(), FiltersConfig(), probability_penalty_mode="flat")
        # flat mode: no penalty within acceptable range → same probability score
        assert s_mid.probability_zone == s_edge.probability_zone

    def test_probability_disabled_mode(self):
        m = make_market(yes_price=0.10)  # extreme, normally penalized
        s = compute_beauty_score(m, ScoringWeights(), FiltersConfig(), probability_penalty_mode="disabled")
        # disabled: always full score on probability
        assert s.probability_zone == 20.0  # full weight

    def test_flat_vs_mid_bias_at_extreme(self):
        m = make_market(yes_price=0.22)
        s_flat = compute_beauty_score(m, ScoringWeights(), FiltersConfig(), probability_penalty_mode="flat")
        s_mid = compute_beauty_score(m, ScoringWeights(), FiltersConfig(), probability_penalty_mode="mid_bias")
        # flat doesn't penalize within range, mid_bias does
        assert s_flat.probability_zone > s_mid.probability_zone

    def test_tighter_spread_scores_higher(self):
        m_tight = make_market(best_bid_yes=0.545, best_ask_yes=0.555)
        m_wide = make_market(best_bid_yes=0.50, best_ask_yes=0.60)
        s_tight = compute_beauty_score(m_tight, ScoringWeights(), FiltersConfig())
        s_wide = compute_beauty_score(m_wide, ScoringWeights(), FiltersConfig())
        assert s_tight.liquidity_depth > s_wide.liquidity_depth
