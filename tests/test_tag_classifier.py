"""Tests for tag-based market type classification."""

from scanner.scan.tag_classifier import classify_from_tags, infer_polymarket_category


class TestClassifyFromTags:
    def test_crypto_tag(self):
        assert classify_from_tags(["Crypto", "Bitcoin"]) == "crypto"

    def test_sports_tag(self):
        assert classify_from_tags(["Sports", "Soccer"]) == "sports"

    def test_political_tag(self):
        assert classify_from_tags(["Politics", "Elections"]) == "political"

    def test_geopolitics_tag(self):
        assert classify_from_tags(["Geopolitics", "Iran"]) == "political"

    def test_economic_tag(self):
        assert classify_from_tags(["Economics", "Federal Reserve"]) == "economic_data"

    def test_tech_tag(self):
        assert classify_from_tags(["AI", "Technology"]) == "tech"

    def test_social_media_tag(self):
        assert classify_from_tags(["Social Media"]) == "social_media"

    def test_no_matching_tags(self):
        assert classify_from_tags(["Unknown", "Random"]) == "other"

    def test_empty_tags(self):
        assert classify_from_tags([]) == "other"

    def test_first_match_wins(self):
        # "Crypto" comes before "Sports" in mapping
        assert classify_from_tags(["Sports", "Crypto"]) == "sports"
        assert classify_from_tags(["Crypto", "Sports"]) == "crypto"

    def test_mixed_relevant_irrelevant(self):
        assert classify_from_tags(["Hide From New", "Sports", "FIFA"]) == "sports"


class TestInferPolymarketCategory:
    """Maps tags → `polymarket_category` key used by fees.calculate_taker_fee.

    Needed because Gamma often omits the top-level `category` field on events;
    without inference the fee falls back to the 0.05 default (see RISK-3 from
    the v0.6.0 review + the real Iran peace-deal case that revealed this).
    """

    def test_geopolitics_tag_maps_to_zero_fee_category(self):
        # Crucial: "Geopolitics" fee category = 0.0, very different from "Politics" = 0.04.
        assert infer_polymarket_category(["Geopolitics", "Iran"]) == "Geopolitics"

    def test_world_events_tag_maps_to_zero_fee_category(self):
        assert infer_polymarket_category(["World Events", "Ukraine"]) == "World Events"

    def test_crypto_tags_map_to_crypto(self):
        assert infer_polymarket_category(["Crypto"]) == "Crypto"
        assert infer_polymarket_category(["Bitcoin"]) == "Crypto"
        assert infer_polymarket_category(["Ethereum"]) == "Crypto"

    def test_sports_tags_map_to_sports(self):
        assert infer_polymarket_category(["Sports"]) == "Sports"
        assert infer_polymarket_category(["Soccer"]) == "Sports"

    def test_politics_tag_without_geopolitics_maps_to_politics(self):
        assert infer_polymarket_category(["Politics"]) == "Politics"
        assert infer_polymarket_category(["Elections"]) == "Politics"

    def test_geopolitics_wins_over_politics_when_both_present(self):
        """Real-world events often carry both tags; the more specific (and
        more favorable to the user) fee category should win.
        """
        assert (
            infer_polymarket_category(["Politics", "Geopolitics"])
            == "Geopolitics"
        )
        assert (
            infer_polymarket_category(["Geopolitics", "Politics"])
            == "Geopolitics"
        )

    def test_tech_tags_map_to_tech(self):
        assert infer_polymarket_category(["AI"]) == "Tech"
        assert infer_polymarket_category(["Technology"]) == "Tech"

    def test_economics_tag(self):
        assert infer_polymarket_category(["Economics"]) == "Economics"
        assert infer_polymarket_category(["Federal Reserve"]) == "Economics"

    def test_social_media_maps_to_mentions(self):
        assert infer_polymarket_category(["Social Media"]) == "Mentions"
        assert infer_polymarket_category(["Twitter"]) == "Mentions"

    def test_no_known_tag_returns_none(self):
        # Caller decides fallback (fees.py uses 0.05 default).
        assert infer_polymarket_category(["Unknown", "Random"]) is None
        assert infer_polymarket_category([]) is None

    def test_all_common_tags_map_to_a_category(self):
        """Smoke: every tag in the priority table maps to a non-None category.

        (Post-2026-04-18 refactor, fees are driven by market.feesEnabled +
        feeSchedule.rate — not by category. This check only guarantees the
        mapping table is internally consistent; category is now a display /
        filter hint, no longer a fee driver.)
        """
        sample_tags = [
            "Geopolitics", "World Events", "Crypto", "Bitcoin", "Ethereum",
            "Sports", "Soccer", "Basketball",
            "Politics", "Elections", "Congress",
            "AI", "Technology",
            "Economics", "Federal Reserve", "Inflation",
            "Weather", "Culture",
            "Social Media", "Twitter",
        ]
        for t in sample_tags:
            cat = infer_polymarket_category([t])
            assert cat is not None, f"tag {t!r} should map to a category"
