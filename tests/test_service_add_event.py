"""Tests for PolilyService.add_event_by_url."""

from unittest.mock import patch

import pytest

from scanner.core.db import PolilyDB
from scanner.tui.service import PolilyService


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


class TestAddEventByUrl:
    @pytest.mark.asyncio
    async def test_adds_event_to_db(self, db):
        service = PolilyService(db=db)
        with patch("scanner.scan.pipeline.fetch_and_score_event") as mock:
            from scanner.core.event_store import EventRow
            from scanner.scan.event_scoring import EventQualityScore
            mock.return_value = {
                "event": EventRow(event_id="ev1", title="Test", updated_at="now"),
                "markets": [],
                "scored_markets": [],
                "event_score": EventQualityScore(total=75),
            }
            result = await service.add_event_by_url("https://polymarket.com/event/test-event")

        assert result is not None
        assert result["event"].event_id == "ev1"

    @pytest.mark.asyncio
    async def test_invalid_url_returns_none(self, db):
        service = PolilyService(db=db)
        result = await service.add_event_by_url("")
        assert result is None

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self, db):
        service = PolilyService(db=db)
        with patch("scanner.scan.pipeline.fetch_and_score_event") as mock:
            mock.return_value = None
            result = await service.add_event_by_url("https://polymarket.com/event/nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_logs_action_to_scan_logs(self, db):
        service = PolilyService(db=db)
        with patch("scanner.scan.pipeline.fetch_and_score_event") as mock:
            from scanner.core.event_store import EventRow
            from scanner.scan.event_scoring import EventQualityScore
            mock.return_value = {
                "event": EventRow(event_id="ev1", title="Test Event", updated_at="now"),
                "markets": [],
                "scored_markets": [],
                "event_score": EventQualityScore(total=75),
            }
            await service.add_event_by_url("https://polymarket.com/event/test-event")

        logs = service.get_scan_logs()
        assert len(logs) >= 1
        assert logs[-1].type == "add_event"
