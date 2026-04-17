"""Tests for ScanService v0.5.0 — DB-first, event-level."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from scanner.analysis_store import get_event_analyses
from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, get_event, upsert_event, upsert_market
from scanner.tui.service import ScanService


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


@pytest.fixture
def service(db):
    from scanner.core.config import ScannerConfig
    config = ScannerConfig()
    return ScanService(config=config, db=db)


def _seed(db, event_id="ev1", market_id="m1", **event_kw):
    # Extract fields that upsert_event intentionally excludes
    tier = event_kw.pop("tier", None)
    structure_score = event_kw.pop("structure_score", None)
    user_status = event_kw.pop("user_status", None)

    defaults = dict(event_id=event_id, title="Test Event", updated_at="now")
    defaults.update(event_kw)
    upsert_event(EventRow(**defaults), db)

    # Set tier/score/user_status directly (upsert_event preserves them)
    if tier is not None or structure_score is not None or user_status is not None:
        updates, vals = [], []
        if tier is not None:
            updates.append("tier = ?")
            vals.append(tier)
        if structure_score is not None:
            updates.append("structure_score = ?")
            vals.append(structure_score)
        if user_status is not None:
            updates.append("user_status = ?")
            vals.append(user_status)
        vals.append(event_id)
        db.conn.execute(
            f"UPDATE events SET {', '.join(updates)} WHERE event_id = ?", vals,
        )
        db.conn.commit()

    upsert_market(MarketRow(
        market_id=market_id, event_id=event_id, question="Will X?",
        yes_price=0.55, no_price=0.45, updated_at="now",
    ), db)


class TestGetAllEvents:
    def test_returns_all_tiers(self, db, service):
        _seed(db, "ev1", "m1", tier="research", structure_score=80)
        _seed(db, "ev2", "m2", tier="filtered", structure_score=30)
        events = service.get_all_events()
        event_ids = [e["event"].event_id for e in events]
        assert "ev1" in event_ids
        assert "ev2" in event_ids


class TestGetEventDetail:
    def test_returns_full_detail(self, db, service):
        _seed(db, "ev1", "m1")
        upsert_market(MarketRow(market_id="m2", event_id="ev1", question="Q2",
                                yes_price=0.3, updated_at="now"), db)
        detail = service.get_event_detail("ev1")
        assert detail["event"].event_id == "ev1"
        assert len(detail["markets"]) == 2
        assert "analyses" in detail
        assert "trades" in detail
        assert "monitor" in detail
        assert "movements" in detail

    def test_nonexistent_returns_none(self, db, service):
        assert service.get_event_detail("nonexistent") is None


class TestPassEvent:
    def test_pass_sets_user_status(self, db, service):
        _seed(db, "ev1", "m1")
        service.pass_event("ev1")
        event = get_event("ev1", db)
        assert event.user_status == "pass"


class TestToggleMonitor:
    def test_enable_monitor(self, db, service):
        _seed(db, "ev1", "m1")
        service.toggle_monitor("ev1", enable=True)
        assert service.get_monitor_count() == 1

    def test_disable_monitor(self, db, service):
        _seed(db, "ev1", "m1")
        service.toggle_monitor("ev1", enable=True)
        service.toggle_monitor("ev1", enable=False)
        assert service.get_monitor_count() == 0


class TestPaperTrades:
    def test_create_and_get_trades(self, db, service):
        """execute_buy creates a position surfaced by get_open_trades (post-v0.6.0)."""
        _seed(db, "ev1", "m1")
        with patch(
            "scanner.core.trade_engine.TradeEngine._fetch_live_price",
            return_value=0.55,
        ):
            service.execute_buy(market_id="m1", side="yes", shares=10.0)
        trades = service.get_open_trades()
        assert len(trades) == 1
        assert trades[0]["side"] == "yes"
        assert trades[0]["entry_price"] == pytest.approx(0.55)

    def test_trade_stats(self, db, service):
        _seed(db, "ev1", "m1")
        service.create_paper_trade(
            event_id="ev1", market_id="m1", title="Test",
            side="yes", entry_price=0.5, position_size_usd=20,
        )
        stats = service.get_trade_stats()
        assert stats["open"] == 1


class TestAnalyzeEvent:
    def test_analyze_saves_to_db(self, db, service):
        _seed(db, "ev1", "m1")
        from scanner.agents.schemas import NarrativeWriterOutput
        mock_output = NarrativeWriterOutput(
            event_id="ev1", summary="test analysis", action="WATCH",
            next_check_at="2026-04-15T12:00:00", next_check_reason="test",
        )
        with patch("scanner.tui.service.NarrativeWriterAgent") as MockAgent:
            instance = MockAgent.return_value
            instance.generate = AsyncMock(return_value=mock_output)
            asyncio.run(service.analyze_event("ev1"))

        analyses = get_event_analyses("ev1", db)
        assert len(analyses) == 1
        assert analyses[0].trigger_source == "manual"


class TestCancelAnalysis:
    def test_cancel_no_error(self, service):
        service.cancel_analysis()  # should not raise


class TestNotifications:
    def test_unread_count(self, db, service):
        db.conn.execute(
            "INSERT INTO notifications (created_at, title, body) VALUES (?, ?, ?)",
            ("2026-04-10", "test", "body"),
        )
        db.conn.commit()
        assert service.get_unread_notification_count() == 1


class TestScanLogs:
    def test_get_scan_logs_empty(self, service):
        logs = service.get_scan_logs()
        assert logs == []


class TestHistoryCount:
    def test_history_count(self, db, service):
        assert service.get_history_count() == 0
