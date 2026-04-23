"""Tests for analysis store — event-level."""
import pytest

from polily.analysis_store import (
    AnalysisVersion,
    append_analysis,
    get_event_analyses,
)
from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, upsert_event


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def _setup_event(db, event_id="ev1"):
    upsert_event(EventRow(event_id=event_id, title=f"Event {event_id}", updated_at="now"), db)


class TestAnalysisStore:
    def test_append_and_get(self, db):
        _setup_event(db)
        version = AnalysisVersion(
            version=1, created_at="2026-04-10T12:00:00",
            trigger_source="manual",
            prices_snapshot={"m1": {"yes": 0.55, "no": 0.45}},
            narrative_output={"action": "WATCH", "summary": "test"},
        )
        append_analysis("ev1", version, db)
        versions = get_event_analyses("ev1", db)
        assert len(versions) == 1
        assert versions[0].trigger_source == "manual"
        assert "m1" in versions[0].prices_snapshot

    def test_multiple_versions(self, db):
        _setup_event(db)
        for i in range(1, 4):
            v = AnalysisVersion(
                version=i, created_at=f"2026-04-{10+i}T12:00:00",
                trigger_source="scan" if i == 1 else "scheduled",
                narrative_output={"action": "WATCH", "summary": f"v{i}"},
            )
            append_analysis("ev1", v, db)
        versions = get_event_analyses("ev1", db)
        assert len(versions) == 3
        assert versions[0].version == 1
        assert versions[2].version == 3

    def test_empty_result(self, db):
        versions = get_event_analyses("nonexistent", db)
        assert versions == []

    def test_prices_snapshot_roundtrip(self, db):
        _setup_event(db)
        snapshot = {"m1": {"yes": 0.6, "bid": 0.59}, "m2": {"yes": 0.3, "bid": 0.29}}
        v = AnalysisVersion(
            version=1, created_at="2026-04-10T12:00:00",
            prices_snapshot=snapshot,
            narrative_output={"action": "BUY_YES"},
        )
        append_analysis("ev1", v, db)
        loaded = get_event_analyses("ev1", db)
        assert loaded[0].prices_snapshot == snapshot

    def test_score_and_mispricing(self, db):
        _setup_event(db)
        v = AnalysisVersion(
            version=1, created_at="2026-04-10T12:00:00",
            narrative_output={"action": "PASS"},
            structure_score=82.5,
            score_breakdown={"liquidity": 25, "verifiability": 20},
            mispricing_signal="moderate",
            mispricing_details="Model 0.49 vs market 0.55",
        )
        append_analysis("ev1", v, db)
        loaded = get_event_analyses("ev1", db)
        assert loaded[0].structure_score == 82.5
        assert loaded[0].mispricing_signal == "moderate"
        assert loaded[0].score_breakdown["liquidity"] == 25

    def test_elapsed_seconds(self, db):
        _setup_event(db)
        v = AnalysisVersion(
            version=1, created_at="2026-04-10T12:00:00",
            narrative_output={"action": "PASS"},
            elapsed_seconds=45.3,
        )
        append_analysis("ev1", v, db)
        loaded = get_event_analyses("ev1", db)
        assert loaded[0].elapsed_seconds == 45.3
