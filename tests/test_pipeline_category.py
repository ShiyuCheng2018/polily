"""Tests for polymarket_category persistence through the Gamma pipeline."""

from scanner.api import parse_gamma_event
from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, get_event, upsert_event


def test_event_row_accepts_polymarket_category():
    row = EventRow(event_id="e1", title="T", polymarket_category="Crypto")
    assert row.polymarket_category == "Crypto"


def test_event_row_defaults_category_to_none():
    row = EventRow(event_id="e1", title="T")
    assert row.polymarket_category is None


def test_upsert_persists_category(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    row = EventRow(event_id="e1", title="T", polymarket_category="Crypto")
    upsert_event(row, db)
    e = get_event("e1", db)
    assert e is not None
    assert e.polymarket_category == "Crypto"


def test_upsert_updates_category_when_provided(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="e1", title="T", polymarket_category="Crypto"), db)
    upsert_event(EventRow(event_id="e1", title="T", polymarket_category="Sports"), db)
    e = get_event("e1", db)
    assert e.polymarket_category == "Sports"


def test_upsert_preserves_category_when_new_row_has_none(tmp_path):
    """Regression: if Gamma hiccups and re-upsert omits category, keep prior value.

    Matches the user_status / structure_score / tier preservation convention.
    """
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="e1", title="T", polymarket_category="Crypto"), db)
    upsert_event(EventRow(event_id="e1", title="T", polymarket_category=None), db)
    e = get_event("e1", db)
    assert e.polymarket_category == "Crypto"


def test_parse_gamma_event_extracts_category():
    gamma_payload = {
        "id": "e1",
        "title": "BTC up this week?",
        "slug": "btc-up",
        "category": "Crypto",
        "tags": [{"label": "Bitcoin", "slug": "btc"}],
        "markets": [],
    }
    event_row, _markets = parse_gamma_event(gamma_payload)
    assert event_row.polymarket_category == "Crypto"


def test_parse_gamma_event_missing_category_is_none():
    gamma_payload = {
        "id": "e1",
        "title": "Some event",
        "slug": "some-event",
        "tags": [],
        "markets": [],
    }
    event_row, _markets = parse_gamma_event(gamma_payload)
    assert event_row.polymarket_category is None


def test_parse_gamma_event_empty_string_category_normalized_to_none():
    """Gamma occasionally returns "" for unclassified events — normalize so the
    null-preservation path in upsert_event fires correctly."""
    gamma_payload = {
        "id": "e1",
        "title": "Event",
        "slug": "s",
        "category": "",
        "tags": [],
        "markets": [],
    }
    event_row, _markets = parse_gamma_event(gamma_payload)
    assert event_row.polymarket_category is None


def test_parse_gamma_event_falls_back_to_tag_inference_when_category_missing():
    """Real case: Gamma response for event 357807 (US x Iran peace deal) has
    no `category` field but tags include "Geopolitics". User paid the 0.05
    default fee when Geopolitics should be 0%. Fix: infer from tags.
    """
    gamma_payload = {
        "id": "e1",
        "title": "US x Iran peace deal?",
        "slug": "iran",
        # no "category" field at all — exactly what Gamma returns
        "tags": [
            {"label": "Iran", "slug": "iran"},
            {"label": "Geopolitics", "slug": "geopolitics"},
            {"label": "Politics", "slug": "politics"},
        ],
        "markets": [],
    }
    event_row, _ = parse_gamma_event(gamma_payload)
    # Geopolitics takes priority over Politics (0% vs 4% fee).
    assert event_row.polymarket_category == "Geopolitics"


def test_parse_gamma_event_gamma_category_wins_over_tag_inference():
    """If Gamma *does* return a category, trust it — don't override with tags."""
    gamma_payload = {
        "id": "e1",
        "title": "T",
        "slug": "s",
        "category": "Politics",
        "tags": [{"label": "Geopolitics", "slug": "geo"}],
        "markets": [],
    }
    event_row, _ = parse_gamma_event(gamma_payload)
    # Gamma says Politics even though tags say Geopolitics — Gamma is authoritative.
    assert event_row.polymarket_category == "Politics"


def test_parse_gamma_event_crypto_tags_without_category():
    """BTC event: Gamma-side we sometimes see only tags; infer Crypto (7.2% fee)."""
    gamma_payload = {
        "id": "e1",
        "title": "BTC over $100k?",
        "slug": "btc",
        "tags": [
            {"label": "Bitcoin", "slug": "btc"},
            {"label": "Crypto", "slug": "crypto"},
        ],
        "markets": [],
    }
    event_row, _ = parse_gamma_event(gamma_payload)
    assert event_row.polymarket_category == "Crypto"
