# tests/test_service_emits_events.py
"""v0.8.0 Task 12: ScanService publishes events on mutation using EXISTING methods."""
from unittest.mock import MagicMock

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.core.events import (
    TOPIC_SCAN_UPDATED,
    TOPIC_WALLET_UPDATED,
    EventBus,
)
from scanner.scan_log import claim_pending_scan, insert_pending_scan
from scanner.tui.service import ScanService


@pytest.fixture
def svc_with_bus(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="ev1", title="T", updated_at="now"), db)
    bus = EventBus()
    svc = ScanService(config=cfg, db=db, event_bus=bus)
    yield svc, bus
    db.close()


def test_service_exposes_event_bus(svc_with_bus):
    svc, bus = svc_with_bus
    assert svc.event_bus is bus


def test_publish_scan_update_emits_topic(svc_with_bus):
    svc, bus = svc_with_bus
    received = []
    bus.subscribe(TOPIC_SCAN_UPDATED, lambda p: received.append(p))

    sid = insert_pending_scan(
        event_id="ev1", event_title="T",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="manual", scheduled_reason=None, db=svc.db,
    )
    claim_pending_scan(sid, svc.db)
    svc.publish_scan_update(sid, event_id="ev1", status="completed")

    assert any(r.get("scan_id") == sid and r.get("status") == "completed"
               for r in received)


def test_existing_topup_publishes_wallet_updated(svc_with_bus):
    """EXISTING ScanService.topup() must now publish TOPIC_WALLET_UPDATED."""
    svc, bus = svc_with_bus
    received = []
    bus.subscribe(TOPIC_WALLET_UPDATED, lambda p: received.append(p))

    svc.topup(50.0)  # existing method — NOT wallet_topup

    assert len(received) == 1
    assert received[0]["balance"] == pytest.approx(150.0)


def test_existing_withdraw_publishes_wallet_updated(svc_with_bus):
    svc, bus = svc_with_bus
    received = []
    bus.subscribe(TOPIC_WALLET_UPDATED, lambda p: received.append(p))

    svc.withdraw(30.0)

    assert len(received) == 1
    assert received[0]["balance"] == pytest.approx(70.0)
