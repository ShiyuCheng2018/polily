"""Tests for event and market store operations."""
import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import (
    EventRow,
    MarketRow,
    get_active_markets,
    get_event,
    get_event_markets,
    get_market,
    mark_market_closed,
    update_market_prices,
    upsert_event,
    upsert_market,
)


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


class TestEventCRUD:
    def test_upsert_and_get_event(self, db):
        upsert_event(EventRow(event_id="123", title="Test Event", updated_at="2026-04-10"), db)
        event = get_event("123", db)
        assert event is not None
        assert event.title == "Test Event"
        assert event.event_id == "123"

    def test_upsert_updates_existing(self, db):
        upsert_event(EventRow(event_id="1", title="Old Title", updated_at="2026-04-10"), db)
        upsert_event(EventRow(event_id="1", title="New Title", updated_at="2026-04-11"), db)
        event = get_event("1", db)
        assert event.title == "New Title"
        assert event.updated_at == "2026-04-11"

    def test_upsert_preserves_user_status(self, db):
        """Re-upserting from scan must NOT overwrite user_status set by user."""
        upsert_event(EventRow(event_id="1", title="E", updated_at="2026-04-10"), db)
        # User sets PASS
        db.conn.execute("UPDATE events SET user_status='pass' WHERE event_id='1'")
        db.conn.commit()
        # Scan re-upserts (should preserve user_status)
        upsert_event(EventRow(event_id="1", title="E updated", updated_at="2026-04-11"), db)
        event = get_event("1", db)
        assert event.title == "E updated"
        assert event.user_status == "pass"

    def test_upsert_preserves_structure_score(self, db):
        """Re-upserting must NOT overwrite structure_score set by scoring pipeline."""
        upsert_event(EventRow(event_id="1", title="E", updated_at="2026-04-10"), db)
        db.conn.execute("UPDATE events SET structure_score=85.0, tier='research' WHERE event_id='1'")
        db.conn.commit()
        upsert_event(EventRow(event_id="1", title="E updated", updated_at="2026-04-11"), db)
        event = get_event("1", db)
        assert event.structure_score == 85.0
        assert event.tier == "research"

    def test_get_nonexistent_event(self, db):
        assert get_event("nonexistent", db) is None


class TestMarketCRUD:
    def _setup_event(self, db):
        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)

    def test_upsert_and_get_market(self, db):
        self._setup_event(db)
        upsert_market(MarketRow(market_id="m1", event_id="ev1", question="Will X?", updated_at="now"), db)
        market = get_market("m1", db)
        assert market is not None
        assert market.question == "Will X?"

    def test_get_event_markets(self, db):
        self._setup_event(db)
        upsert_market(MarketRow(market_id="m1", event_id="ev1", question="Q1", updated_at="now"), db)
        upsert_market(MarketRow(market_id="m2", event_id="ev1", question="Q2", updated_at="now"), db)
        markets = get_event_markets("ev1", db)
        assert len(markets) == 2

    def test_get_active_markets(self, db):
        self._setup_event(db)
        upsert_market(MarketRow(market_id="m1", event_id="ev1", question="Q1", updated_at="now"), db)
        upsert_market(MarketRow(market_id="m2", event_id="ev1", question="Q2", closed=1, updated_at="now"), db)
        active = get_active_markets(db)
        assert len(active) == 1
        assert active[0].market_id == "m1"

    def test_update_market_prices(self, db):
        self._setup_event(db)
        upsert_market(MarketRow(market_id="m1", event_id="ev1", question="Q", updated_at="now"), db)
        update_market_prices("m1", yes_price=0.6, no_price=0.4, best_bid=0.59, best_ask=0.61,
                           spread=0.02, bid_depth=500.0, ask_depth=300.0, db=db)
        market = get_market("m1", db)
        assert market.yes_price == 0.6
        assert market.no_price == 0.4
        assert market.best_bid == 0.59
        assert market.bid_depth == 500.0

    def test_mark_market_closed(self, db):
        self._setup_event(db)
        upsert_market(MarketRow(market_id="m1", event_id="ev1", question="Q", updated_at="now"), db)
        mark_market_closed("m1", db)
        market = get_market("m1", db)
        assert market.closed == 1
        assert market.accepting_orders == 0

    def test_get_nonexistent_market(self, db):
        assert get_market("nonexistent", db) is None


def test_market_row_roundtrips_resolved_outcome(tmp_path):
    """MarketRow must expose resolved_outcome end-to-end: DB → ORM → .attr."""
    from datetime import UTC, datetime
    db = PolilyDB(tmp_path / "t.db")
    now = datetime.now(UTC).isoformat()
    db.conn.execute(
        "INSERT INTO events (event_id, title, tags, updated_at) VALUES (?,?,'[]',?)",
        ("e1", "test", now),
    )
    db.conn.execute(
        "INSERT INTO markets (market_id, event_id, question, outcomes, "
        "closed, resolved_outcome, updated_at) "
        "VALUES (?, ?, 'Q', '[\"Yes\",\"No\"]', 1, 'no', ?)",
        ("m1", "e1", now),
    )
    db.conn.commit()

    m = get_market("m1", db)
    assert m is not None
    assert m.resolved_outcome == "no"
    db.close()


def test_market_row_default_resolved_outcome_is_none():
    """MarketRow should default resolved_outcome to None."""
    m = MarketRow(market_id="m1", event_id="e1", question="Q")
    assert m.resolved_outcome is None


def test_upsert_preserves_resolved_outcome(tmp_path):
    """upsert_market must NOT clobber resolved_outcome — it's owned by
    ResolutionHandler and sits outside _MARKET_INSERT_COLS by design.

    Regression guard: if a well-meaning future dev adds 'resolved_outcome'
    to _MARKET_INSERT_COLS, this test fails loudly because a routine
    Gamma-driven upsert would overwrite the settled outcome.
    """
    from datetime import UTC, datetime
    db = PolilyDB(tmp_path / "t.db")

    # Seed event + market with resolved_outcome='no' via raw SQL
    # (mimics a ResolutionHandler.resolve_market write)
    now = datetime.now(UTC).isoformat()
    db.conn.execute(
        "INSERT INTO events (event_id, title, tags, updated_at) VALUES (?,?,'[]',?)",
        ("e1", "test event", now),
    )
    db.conn.execute(
        "INSERT INTO markets (market_id, event_id, question, outcomes, "
        "closed, resolved_outcome, updated_at) "
        "VALUES ('m1', 'e1', 'Q', '[\"Yes\",\"No\"]', 1, 'no', ?)",
        (now,),
    )
    db.conn.commit()

    # Now upsert a fresh MarketRow for the same market_id (simulates a
    # Gamma refresh). MarketRow defaults resolved_outcome to None — if
    # that leaks into the UPDATE, we'd wipe 'no' to NULL.
    fresh = MarketRow(
        market_id="m1", event_id="e1", question="Q",
        closed=1,
    )
    upsert_market(fresh, db)

    # Verify: resolved_outcome UNCHANGED
    m = get_market("m1", db)
    assert m is not None
    assert m.resolved_outcome == "no", (
        "upsert_market leaked resolved_outcome into update — "
        "likely a regression from adding it to _MARKET_INSERT_COLS"
    )
    db.close()
