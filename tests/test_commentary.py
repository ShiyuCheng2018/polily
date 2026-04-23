"""Tests for polily.scan.commentary module."""


from polily.scan.commentary import (
    _level_index,
    _match_condition,
    _normalize_pct,
    _pick_variant,
    generate_commentary,
    get_dimension_phrase,
)

# ---------------------------------------------------------------------------
# _normalize_pct
# ---------------------------------------------------------------------------

class TestNormalizePct:
    def test_zero_zero(self):
        assert _normalize_pct(0, 0) == 0.0

    def test_half(self):
        assert _normalize_pct(50, 100) == 50.0

    def test_full(self):
        assert _normalize_pct(100, 100) == 100.0

    def test_over_cap(self):
        assert _normalize_pct(150, 100) == 100.0

    def test_negative_score(self):
        assert _normalize_pct(-10, 100) == 0.0

    def test_negative_max(self):
        assert _normalize_pct(50, -5) == 0.0

    def test_small_fraction(self):
        result = _normalize_pct(3, 30)
        assert abs(result - 10.0) < 0.01

    def test_weighted_score(self):
        # 15 out of max weight 22 => ~68.18%
        result = _normalize_pct(15, 22)
        assert abs(result - 68.18) < 0.1


# ---------------------------------------------------------------------------
# _level_index
# ---------------------------------------------------------------------------

class TestLevelIndex:
    def test_zero(self):
        assert _level_index(0) == 0

    def test_just_below_5(self):
        assert _level_index(4.9) == 0

    def test_at_5(self):
        assert _level_index(5) == 1

    def test_at_99(self):
        assert _level_index(99) == 19

    def test_at_100(self):
        assert _level_index(100) == 19  # capped at 19

    def test_at_50(self):
        assert _level_index(50) == 10

    def test_at_95(self):
        assert _level_index(95) == 19


# ---------------------------------------------------------------------------
# _pick_variant
# ---------------------------------------------------------------------------

class TestPickVariant:
    def test_deterministic(self):
        v1 = _pick_variant("abc123", "liquidity", 3)
        v2 = _pick_variant("abc123", "liquidity", 3)
        assert v1 == v2

    def test_within_range(self):
        for i in range(20):
            v = _pick_variant(f"market_{i}", "time", 3)
            assert 0 <= v < 3

    def test_different_inputs_vary(self):
        """Different market_ids should produce at least some different variants."""
        variants = {_pick_variant(f"market_{i}", "liquidity", 3) for i in range(50)}
        # With 50 different inputs and 3 variants, we expect at least 2 distinct values
        assert len(variants) >= 2

    def test_different_dimensions(self):
        v1 = _pick_variant("same_market", "liquidity", 3)
        v2 = _pick_variant("same_market", "time", 3)
        # They may or may not differ, but both should be valid
        assert 0 <= v1 < 3
        assert 0 <= v2 < 3


# ---------------------------------------------------------------------------
# get_dimension_phrase
# ---------------------------------------------------------------------------

class TestGetDimensionPhrase:
    def test_returns_string(self):
        phrase = get_dimension_phrase("liquidity", 15, 30, "test_market")
        assert isinstance(phrase, str)
        assert len(phrase) > 0

    def test_correct_level_low(self):
        """Score 0 out of 30 => pct 0 => level 0 => one of the first-level phrases."""
        phrase = get_dimension_phrase("liquidity", 0, 30, "test_market")
        level_0_phrases = ["鬼都不来交易", "挂单？挂给谁看", "这盘口是摆设"]
        assert phrase in level_0_phrases

    def test_correct_level_high(self):
        """Score 30 out of 30 => pct 100 => level 19 => one of the last-level phrases."""
        phrase = get_dimension_phrase("liquidity", 30, 30, "test_market")
        level_19_phrases = ["想买多少买多少", "随便造", "盘口深不见底"]
        assert phrase in level_19_phrases

    def test_all_dimensions(self):
        """All 6 dimensions should return phrases without error."""
        for dim in ["liquidity", "verifiability", "probability", "time", "friction", "net_edge"]:
            phrase = get_dimension_phrase(dim, 5, 10, "test_id")
            assert isinstance(phrase, str)
            assert len(phrase) > 0


# ---------------------------------------------------------------------------
# generate_commentary
# ---------------------------------------------------------------------------

class TestGenerateCommentary:
    def test_returns_all_keys(self):
        breakdown = {
            "liquidity": 15,
            "verifiability": 5,
            "probability": 10,
            "time": 8,
            "friction": 5,
        }
        result = generate_commentary(breakdown, 43.0, "test_market_1", "other")
        assert "dim_comments" in result
        assert "overall" in result
        assert "judgment" in result
        assert "strongest_text" in result
        assert "weakest_text" in result
        assert "advice" in result

    def test_overall_non_empty(self):
        breakdown = {
            "liquidity": 15,
            "verifiability": 5,
            "probability": 10,
            "time": 8,
            "friction": 5,
        }
        result = generate_commentary(breakdown, 43.0, "test_market_2", "other")
        assert len(result["overall"]) > 0

    def test_dim_comments_populated(self):
        breakdown = {
            "liquidity": 15,
            "verifiability": 5,
            "probability": 10,
            "time": 8,
            "friction": 5,
        }
        result = generate_commentary(breakdown, 43.0, "test_market_3", "other")
        # Should have comments for all 5 base dimensions
        assert len(result["dim_comments"]) >= 5

    def test_crypto_includes_net_edge(self):
        breakdown = {
            "liquidity": 10,
            "verifiability": 5,
            "probability": 8,
            "time": 9,
            "friction": 5,
            "net_edge": 12,
        }
        result = generate_commentary(breakdown, 49.0, "crypto_test", "crypto")
        assert "net_edge" in result["dim_comments"]

    def test_non_crypto_no_net_edge(self):
        breakdown = {
            "liquidity": 15,
            "verifiability": 5,
            "probability": 10,
            "time": 8,
            "friction": 5,
        }
        result = generate_commentary(breakdown, 43.0, "pol_test", "political")
        assert "net_edge" not in result["dim_comments"]

    def test_judgment_matches_range(self):
        # Low score
        result = generate_commentary(
            {"liquidity": 2, "verifiability": 1, "probability": 2, "time": 1, "friction": 1},
            7.0, "low_test", "other",
        )
        low_phrases = ["这市场烂透了，碰都别碰", "结构全面崩坏，纯粹浪费时间", "垃圾市场，下一个"]
        assert result["judgment"] in low_phrases

        # High score
        result = generate_commentary(
            {"liquidity": 28, "verifiability": 9, "probability": 18, "time": 23, "friction": 14},
            92.0, "high_test", "other",
        )
        high_phrases = ["教科书级的市场结构", "顶级交易机会", "很少能遇到这么好的"]
        assert result["judgment"] in high_phrases

    def test_deterministic_same_market(self):
        """Same inputs => same output."""
        bd = {"liquidity": 15, "verifiability": 5, "probability": 10, "time": 8, "friction": 5}
        r1 = generate_commentary(bd, 43.0, "stable_id", "other")
        r2 = generate_commentary(bd, 43.0, "stable_id", "other")
        assert r1 == r2


# ---------------------------------------------------------------------------
# _match_condition
# ---------------------------------------------------------------------------

class TestMatchCondition:
    def test_total_gte_match(self):
        assert _match_condition({"total_gte": 50}, 60, {}, False) is True

    def test_total_gte_no_match(self):
        assert _match_condition({"total_gte": 50}, 40, {}, False) is False

    def test_total_lt_match(self):
        assert _match_condition({"total_lt": 75}, 60, {}, False) is True

    def test_total_lt_no_match(self):
        assert _match_condition({"total_lt": 75}, 80, {}, False) is False

    def test_pct_gte_match(self):
        assert _match_condition(
            {"liquidity_pct_gte": 50}, 0, {"liquidity": 60}, False,
        ) is True

    def test_pct_lt_match(self):
        assert _match_condition(
            {"liquidity_pct_lt": 30}, 0, {"liquidity": 20}, False,
        ) is True

    def test_is_crypto_true(self):
        assert _match_condition({"is_crypto": True}, 0, {}, True) is True
        assert _match_condition({"is_crypto": True}, 0, {}, False) is False

    def test_is_crypto_false(self):
        assert _match_condition({"is_crypto": False}, 0, {}, False) is True
        assert _match_condition({"is_crypto": False}, 0, {}, True) is False

    def test_combined_conditions(self):
        cond = {"total_gte": 70, "net_edge_pct_lt": 5, "is_crypto": False}
        # All conditions match
        assert _match_condition(cond, 80, {"net_edge": 3}, False) is True
        # total too low
        assert _match_condition(cond, 60, {"net_edge": 3}, False) is False
        # net_edge too high
        assert _match_condition(cond, 80, {"net_edge": 10}, False) is False
        # is_crypto wrong
        assert _match_condition(cond, 80, {"net_edge": 3}, True) is False

    def test_missing_dim_defaults_to_zero(self):
        """Missing dimension in dim_pcts should default to 0."""
        assert _match_condition(
            {"net_edge_pct_gte": 50}, 0, {}, False,
        ) is False  # 0 < 50
        assert _match_condition(
            {"net_edge_pct_lt": 50}, 0, {}, False,
        ) is True  # 0 < 50

    def test_empty_condition_always_matches(self):
        """Fallback condition with total_gte: 0 matches everything."""
        assert _match_condition({"total_gte": 0}, 0, {}, False) is True
        assert _match_condition({"total_gte": 0}, 100, {}, True) is True
