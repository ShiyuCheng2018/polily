"""Tests for tag-based market type classification."""

from scanner.scan.tag_classifier import classify_from_tags


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
