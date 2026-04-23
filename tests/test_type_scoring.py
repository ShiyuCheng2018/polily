"""Tests for type-specific market scoring weights + net edge."""

from datetime import UTC, datetime, timedelta

from polily.scan.mispricing import MispricingResult
from polily.scan.scoring import compute_structure_score
from tests.conftest import make_market


class TestTypeSpecificWeights:
    def test_crypto_has_net_edge_dimension(self):
        m = make_market(
            market_type="crypto", yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        score = compute_structure_score(m)
        assert hasattr(score, "net_edge")

    def test_sports_net_edge_is_zero(self):
        m = make_market(
            market_type="sports", yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        score = compute_structure_score(m)
        assert score.net_edge == 0.0

    def test_crypto_total_still_100(self):
        m = make_market(
            market_type="crypto", yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        score = compute_structure_score(m)
        assert 0 <= score.total <= 100

    def test_same_market_different_type_different_weights(self):
        kwargs = dict(
            yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        m_crypto = make_market(market_type="crypto", **kwargs)
        m_sports = make_market(market_type="sports", **kwargs)
        s_crypto = compute_structure_score(m_crypto)
        s_sports = compute_structure_score(m_sports)
        assert s_crypto.liquidity_structure <= s_sports.liquidity_structure


class TestNetEdgeWithMispricing:
    def test_crypto_with_mispricing_gets_net_edge(self):
        """Crypto market with mispricing deviation → net_edge > 0."""
        m = make_market(
            market_type="crypto", yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        mp = MispricingResult(signal="moderate", deviation_pct=0.08, direction="underpriced")
        score = compute_structure_score(m, mispricing=mp)
        assert score.net_edge > 0  # 8% deviation - ~4% friction = ~4% net edge

    def test_crypto_no_mispricing_net_edge_zero(self):
        """Crypto market without mispricing → net_edge = 0."""
        m = make_market(
            market_type="crypto", yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        score = compute_structure_score(m)
        assert score.net_edge == 0.0

    def test_sports_with_mispricing_still_zero(self):
        """Sports market ignores mispricing (weight=0)."""
        m = make_market(
            market_type="sports", yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        mp = MispricingResult(signal="moderate", deviation_pct=0.08, direction="underpriced")
        score = compute_structure_score(m, mispricing=mp)
        assert score.net_edge == 0.0

    def test_crypto_high_edge_scores_high(self):
        """Large mispricing → high net_edge score."""
        m = make_market(
            market_type="crypto", yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        mp_big = MispricingResult(signal="strong", deviation_pct=0.15, direction="underpriced")
        mp_small = MispricingResult(signal="weak", deviation_pct=0.03, direction="underpriced")
        s_big = compute_structure_score(m, mispricing=mp_big)
        s_small = compute_structure_score(m, mispricing=mp_small)
        assert s_big.net_edge > s_small.net_edge
        assert s_big.total > s_small.total
