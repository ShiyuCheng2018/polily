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

    def test_trades_reflects_v060_positions_not_legacy_paper_trades(self, db, service):
        """Regression: after v0.6.0 the TUI MarketDetailView's 'trades' feed
        must reflect the live `positions` table (TradeEngine.execute_buy only
        writes there). Reading legacy `paper_trades` shows stale/empty data.

        Test shape: buy through TradeEngine (mock live price), then confirm
        get_event_detail exposes a PositionPanel-compatible row."""
        from unittest.mock import patch as _patch
        _seed(db, "ev1", "m1")
        with _patch(
            "scanner.core.trade_engine.TradeEngine._fetch_live_price",
            return_value=0.79,
        ):
            service.execute_buy(market_id="m1", side="no", shares=10.0)

        detail = service.get_event_detail("ev1")
        trades = detail["trades"]
        assert len(trades) == 1, (
            f"expected 1 trade row derived from positions, got {len(trades)}"
        )
        t = trades[0]
        # PositionPanel reads: market_id, side, entry_price, position_size_usd, title.
        assert t["market_id"] == "m1"
        assert t["side"] == "no"
        assert t["entry_price"] == pytest.approx(0.79)
        assert t["position_size_usd"] == pytest.approx(7.90)  # 10 × 0.79
        assert "title" in t


class TestComputePositionContext:
    """Regression: has_position + position_summary in analyze_event must
    source from the v0.6.0 positions table (TradeEngine's sole write target),
    not the legacy paper_trades table. Shape is shared with the AI
    narrative-writer prompt, so fields must survive mapping:
      avg_cost → entry_price line
      cost_basis → size line
    """

    def test_no_positions_returns_false_none(self, db, service):
        _seed(db, "ev1", "m1")
        has_pos, summary = service._compute_position_context("ev1")
        assert has_pos is False
        assert summary is None

    def test_positions_populate_summary_lines(self, db, service):
        from unittest.mock import patch as _patch
        _seed(db, "ev1", "m1")
        with _patch(
            "scanner.core.trade_engine.TradeEngine._fetch_live_price",
            return_value=0.50,
        ):
            service.execute_buy(market_id="m1", side="no", shares=10.0)

        has_pos, summary = service._compute_position_context("ev1")
        assert has_pos is True
        assert summary is not None
        assert "NO" in summary
        assert "0.50" in summary  # avg_cost rendered
        assert "$5" in summary    # cost_basis ≈ 5
        assert "m1" in summary

    def test_ignores_legacy_paper_trades_rows(self, db, service):
        """paper_trades row on the same event must not produce a summary —
        positions is the source of truth. Guards against silent v0.5.x leak."""
        from scanner.core.paper_store import create_paper_trade
        _seed(db, "ev1", "m1")
        create_paper_trade(
            event_id="ev1", market_id="m1", title="legacy",
            side="yes", entry_price=0.55, position_size_usd=20.0, db=db,
        )
        has_pos, summary = service._compute_position_context("ev1")
        assert has_pos is False
        assert summary is None


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
