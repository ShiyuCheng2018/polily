"""Tests for Polymarket URL parsing."""

from scanner.url_parser import parse_polymarket_url


class TestParsePolymarketUrl:
    def test_full_event_url(self):
        result = parse_polymarket_url("https://polymarket.com/event/bitcoin-above-on-april-16")
        assert result == "bitcoin-above-on-april-16"

    def test_event_url_with_market_suffix(self):
        result = parse_polymarket_url(
            "https://polymarket.com/event/bitcoin-above-on-april-16/bitcoin-above-74000"
        )
        assert result == "bitcoin-above-on-april-16"

    def test_bare_slug(self):
        result = parse_polymarket_url("bitcoin-above-on-april-16")
        assert result == "bitcoin-above-on-april-16"

    def test_url_without_https(self):
        result = parse_polymarket_url("polymarket.com/event/us-iran-peace-deal")
        assert result == "us-iran-peace-deal"

    def test_url_with_query_params(self):
        result = parse_polymarket_url("https://polymarket.com/event/my-event?ref=abc")
        assert result == "my-event"

    def test_empty_returns_none(self):
        assert parse_polymarket_url("") is None

    def test_invalid_url_returns_none(self):
        assert parse_polymarket_url("https://google.com/something") is None
