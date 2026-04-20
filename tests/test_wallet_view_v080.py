"""v0.8.0 Task 18: wallet view migrated to atoms + events + footer hints."""
from unittest.mock import MagicMock, patch
import pytest

from scanner.core.db import PolilyDB
from scanner.core.events import EventBus, TOPIC_WALLET_UPDATED
from scanner.tui.service import ScanService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "w.db")
    yield ScanService(config=cfg, db=db, event_bus=EventBus())
    db.close()


async def test_wallet_view_uses_atoms(svc):
    """Both PolilyCard AND PolilyZone must appear (balance=card, ledger=zone)."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.wallet import WalletView
    from scanner.tui.widgets.polily_card import PolilyCard
    from scanner.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = WalletView(svc)
        await app.mount(view)
        await pilot.pause()
        card_count = len(list(view.query(PolilyCard)))
        zone_count = len(list(view.query(PolilyZone)))
        assert card_count >= 1, f"wallet should show balance in PolilyCard (found {card_count})"
        assert zone_count >= 1, f"wallet should use PolilyZone for ledger (found {zone_count})"


async def test_wallet_view_chinese_labels_rendered(svc):
    """Labels appear in actual mounted widgets."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.wallet import WalletView
    from textual.widgets import Static, Label

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = WalletView(svc)
        await app.mount(view)
        await pilot.pause()
        # Collect text from Static/Label descendants.
        # Textual 8.x exposes content (not renderable) on Static; fall back gracefully.
        texts = []
        for s in view.query(Static):
            val = getattr(s, "renderable", None) or getattr(s, "content", None)
            if val is not None:
                texts.append(str(val))
        for lbl in view.query(Label):
            val = getattr(lbl, "renderable", None) or getattr(lbl, "content", None)
            if val is not None:
                texts.append(str(val))
        joined = " ".join(texts)
        for lbl in ("余额", "浮动盈亏", "累计已实现"):
            assert lbl in joined, f"label {lbl} missing from rendered wallet view"


async def test_wallet_view_bus_callback_uses_call_from_thread(svc):
    """Publish TOPIC_WALLET_UPDATED; verify view's callback invokes call_from_thread."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.wallet import WalletView

    called = []
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = WalletView(svc)
        await app.mount(view)
        await pilot.pause()
        original = app.call_from_thread
        def spy(fn, *a, **kw):
            called.append(getattr(fn, "__name__", str(fn)))
            return original(fn, *a, **kw)
        with patch.object(app, "call_from_thread", side_effect=spy):
            svc.event_bus.publish(TOPIC_WALLET_UPDATED, {"balance": 200.0, "source": "topup"})
            await pilot.pause()
        assert any("render" in n.lower() or "refresh" in n.lower() or "update" in n.lower() for n in called), \
            f"bus callback did not invoke render/refresh via call_from_thread: {called}"


def test_wallet_view_bindings_match_sf4_decision():
    """SF4: keep t/w, add r. All 3 must have show=True for footer display."""
    from scanner.tui.views.wallet import WalletView
    keys = {b.key: b.show for b in WalletView.BINDINGS}
    assert keys.get("t") is True, f"topup binding missing or hidden: {keys}"
    assert keys.get("w") is True, f"withdraw binding missing or hidden: {keys}"
    assert keys.get("r") is True, f"reset binding missing or hidden: {keys}"
