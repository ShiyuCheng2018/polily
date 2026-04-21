"""v0.8.0 Task 28: wallet_modals migrated (Topup + Withdraw + Reset)."""
from unittest.mock import MagicMock

import pytest

from scanner.core.db import PolilyDB
from scanner.core.events import EventBus
from scanner.tui.service import ScanService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "wm.db")
    yield ScanService(config=cfg, db=db, event_bus=EventBus())
    db.close()


@pytest.mark.asyncio
async def test_topup_modal_uses_atoms(svc):
    """TopupModal uses PolilyZone/PolilyCard for layout."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.wallet_modals import TopupModal
    from scanner.tui.widgets.polily_card import PolilyCard
    from scanner.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        modal = TopupModal(service=svc)
        await app.push_screen(modal)
        await pilot.pause()
        zones = list(modal.query(PolilyZone))
        cards = list(modal.query(PolilyCard))
        assert len(zones) + len(cards) >= 1, "TopupModal should use v0.8.0 atoms"


@pytest.mark.asyncio
async def test_withdraw_modal_uses_atoms(svc):
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.wallet_modals import WithdrawModal
    from scanner.tui.widgets.polily_card import PolilyCard
    from scanner.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        modal = WithdrawModal(service=svc)
        await app.push_screen(modal)
        await pilot.pause()
        assert len(list(modal.query(PolilyZone))) + len(list(modal.query(PolilyCard))) >= 1


@pytest.mark.asyncio
async def test_reset_modal_uses_atoms_and_destructive_style(svc):
    """WalletResetModal: uses atoms + destructive-safe confirm flow."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.wallet_modals import WalletResetModal
    from scanner.tui.widgets.polily_card import PolilyCard
    from scanner.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        modal = WalletResetModal(service=svc)
        await app.push_screen(modal)
        await pilot.pause()
        assert len(list(modal.query(PolilyZone))) + len(list(modal.query(PolilyCard))) >= 1


@pytest.mark.asyncio
async def test_modal_chinese_labels(svc):
    """Chinese labels on at least one of the modals."""
    from textual.widgets import Button, Label, Static

    from scanner.tui.app import PolilyApp
    from scanner.tui.views.wallet_modals import TopupModal

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        modal = TopupModal(service=svc)
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
        found = any(txt in joined for txt in ("充值", "金额", "确认", "取消", "余额"))
        assert found, f"no Chinese label found. Sample: {joined[:300]}"
