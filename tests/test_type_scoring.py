"""Tests for type-specific market scoring weights."""

from datetime import UTC, datetime, timedelta

from scanner.core.config import ScoringWeights
from scanner.scan.scoring import compute_structure_score
from tests.conftest import make_market


class TestTypeSpecificWeights:
    def test_crypto_has_net_edge_dimension(self):
        """Crypto markets should have net_edge in their breakdown."""
        m = make_market(
            market_type="crypto",
            yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        score = compute_structure_score(m, ScoringWeights())
        assert hasattr(score, "net_edge")

    def test_sports_net_edge_is_zero(self):
        """Sports markets should have net_edge = 0."""
        m = make_market(
            market_type="sports",
            yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        score = compute_structure_score(m, ScoringWeights())
        assert score.net_edge == 0.0

    def test_crypto_total_still_100(self):
        """Even with net_edge, total should be 0-100."""
        m = make_market(
            market_type="crypto",
            yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        score = compute_structure_score(m, ScoringWeights())
        assert 0 <= score.total <= 100

    def test_same_market_different_type_different_weights(self):
        """Same market data, different type → different score distribution."""
        kwargs = dict(
            yes_price=0.55,
            resolution_time=datetime.now(UTC) + timedelta(days=5),
        )
        m_crypto = make_market(market_type="crypto", **kwargs)
        m_sports = make_market(market_type="sports", **kwargs)

        s_crypto = compute_structure_score(m_crypto, ScoringWeights())
        s_sports = compute_structure_score(m_sports, ScoringWeights())

        # Crypto has lower non-edge weights to make room for net_edge
        assert s_crypto.liquidity_structure <= s_sports.liquidity_structure
