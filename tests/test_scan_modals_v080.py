"""v0.8.0 Task 29: scan_modals migrated — ConfirmCancelScanModal."""
from unittest.mock import MagicMock

import pytest

from polily.core.db import PolilyDB
from polily.core.events import EventBus
from polily.tui.service import PolilyService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "sm.db")
    yield PolilyService(config=cfg, db=db, event_bus=EventBus())
    db.close()


async def test_confirm_cancel_scan_modal_uses_atoms(svc):
    """Modal uses PolilyZone (destructive) or PolilyCard for layout."""
    from polily.tui.app import PolilyApp
    from polily.tui.views.scan_modals import ConfirmCancelScanModal
    from polily.tui.widgets.polily_card import PolilyCard
    from polily.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        modal = ConfirmCancelScanModal(event_title="Test Event", elapsed_seconds=12.5)
        await app.push_screen(modal)
        await pilot.pause()
        zones = list(modal.query(PolilyZone))
        cards = list(modal.query(PolilyCard))
        assert len(zones) + len(cards) >= 1, "modal should use v0.8.0 atoms"


async def test_confirm_cancel_chinese_labels(svc):
    from textual.widgets import Button, Label, Static

    from polily.tui.app import PolilyApp
    from polily.tui.views.scan_modals import ConfirmCancelScanModal

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        modal = ConfirmCancelScanModal(event_title="Test Event", elapsed_seconds=12.5)
        await app.push_screen(modal)
        await pilot.pause()
        texts = []
        for s in modal.query(Static):
            val = getattr(s, "renderable", None) or getattr(s, "content", None)
            if val:
                texts.append(str(val))
        for b in modal.query(Button):
            texts.append(str(b.label))
        for lbl in modal.query(Label):
            val = getattr(lbl, "renderable", None) or getattr(lbl, "content", None)
            if val:
                texts.append(str(val))
        joined = " ".join(texts)
        found = any(txt in joined for txt in ("取消", "确认", "分析", "Test Event"))
        assert found, f"no expected text. Sample: {joined[:300]}"
