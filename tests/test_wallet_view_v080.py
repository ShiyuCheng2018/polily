"""v0.8.0 Task 18: wallet view migrated to atoms + events + footer hints."""
from unittest.mock import MagicMock, patch

import pytest

from scanner.core.db import PolilyDB
from scanner.core.events import TOPIC_WALLET_UPDATED, EventBus
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
    from textual.widgets import Label, Static

    from scanner.tui.app import PolilyApp
    from scanner.tui.views.wallet import WalletView

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
        # v0.8.0 dispatch_to_ui picks `call_later` on UI thread or
        # `call_from_thread` on worker. Patch both so either path is captured.
        def spy_ct(fn, *a, **kw):
            called.append(getattr(fn, "__name__", str(fn)))
        def spy_cl(*args, **kw):
            if len(args) >= 2:
                called.append(getattr(args[1], "__name__", str(args[1])))
        with patch.object(app, "call_from_thread", side_effect=spy_ct), \
             patch.object(app, "call_later", side_effect=spy_cl):
            svc.event_bus.publish(TOPIC_WALLET_UPDATED, {"balance": 200.0, "source": "topup"})
            await pilot.pause()
        assert any("render" in n.lower() or "refresh" in n.lower() or "update" in n.lower() for n in called), \
            f"bus callback did not invoke render/refresh via call_from_thread: {called}"


def test_wallet_view_bindings_match_sf4_decision():
    """SF4 (v0.8.0 update): t/w remain. `r` now means page refresh (every
    view declares its own `r` so the footer reliably shows it). Wallet
    reset moved to `shift+r` so the destructive op keeps a mnemonic key
    but requires a modifier."""
    from scanner.tui.views.wallet import WalletView
    keys = {b.key: (b.show, b.action) for b in WalletView.BINDINGS}
    t = keys.get("t")
    w = keys.get("w")
    r = keys.get("r")
    sr = keys.get("shift+r")
    assert t and t[0] is True, f"topup binding missing or hidden: {keys}"
    assert w and w[0] is True, f"withdraw binding missing or hidden: {keys}"
    assert r and r[0] is True and r[1] == "refresh", \
        f"r should be refresh (show=True): {keys}"
    assert sr and sr[0] is True and sr[1] == "reset", \
        f"shift+r should be reset (show=True): {keys}"


async def test_wallet_view_has_no_redundant_keyhint_line(svc):
    """The '[t] 充值   [w] 提现   [r] 重置' Static was removed — footer
    already surfaces the keys. Checked by absence of the `.hint` class
    Static that previously held the line."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.wallet import WalletView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = WalletView(svc)
        await app.mount(view)
        await pilot.pause()
        hint_statics = list(view.query(".hint"))
        assert not hint_statics, \
            f"expected no '.hint' Static (key hints duplicate footer), found {len(hint_statics)}"


async def test_wallet_balance_card_stable_ids_no_duplication_on_refresh(svc):
    """Regression: rapid _render_all calls (bus callbacks, heartbeat) must
    not leak KVRow / .wallet-dynamic widgets. Pre-fix the card used
    remove+remount which raced Textual's deferred removal."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.wallet import WalletView
    from scanner.tui.widgets.kv_row import KVRow

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = WalletView(svc)
        await app.mount(view)
        await pilot.pause()

        # Repeatedly force sync renders — bypass @once_per_tick to simulate
        # multiple bus ticks having actually run.
        render = type(view)._render_all.__wrapped__
        for _ in range(5):
            render(view)
        await pilot.pause()

        kv_rows = list(view.query(KVRow))
        # Exactly 5: cash, available, positions_value, unrealized, realized.
        assert len(kv_rows) == 5, (
            f"expected exactly 5 KVRows in wallet balance card after 5 "
            f"refreshes, got {len(kv_rows)} — remove+remount pattern "
            f"leaked stale widgets"
        )
        # And exactly 2 .wallet-dynamic Statics (headline + footnote).
        dynamics = list(view.query(".wallet-dynamic"))
        assert len(dynamics) == 2, (
            f"expected 2 .wallet-dynamic Statics, got {len(dynamics)}"
        )


def test_every_content_view_declares_visible_r_refresh():
    """Per v0.8.0 polish: every content view binds `r` → action_refresh
    with show=True so the footer surfaces it uniformly. Intentionally
    page-level (not global): each view owns its refresh semantics, even
    though most already auto-update via EventBus."""
    from scanner.tui.views.archived_events import ArchivedEventsView
    from scanner.tui.views.event_detail import EventDetailView
    from scanner.tui.views.history import HistoryView
    from scanner.tui.views.monitor_list import MonitorListView
    from scanner.tui.views.paper_status import PaperStatusView
    from scanner.tui.views.scan_log import ScanLogDetailView, ScanLogView
    from scanner.tui.views.score_result import ScoreResultView
    from scanner.tui.views.wallet import WalletView

    views = [
        ArchivedEventsView, EventDetailView, HistoryView, MonitorListView,
        PaperStatusView, ScanLogDetailView, ScanLogView, ScoreResultView,
        WalletView,
    ]
    for view in views:
        r_bindings = [b for b in view.BINDINGS if b.key == "r"]
        assert r_bindings, f"{view.__name__} is missing an `r` binding"
        b = r_bindings[0]
        assert b.action == "refresh", \
            f"{view.__name__}.r should map to action=refresh, got {b.action!r}"
        assert b.show is True, \
            f"{view.__name__}.r must have show=True so the footer shows it"
        assert hasattr(view, "action_refresh"), \
            f"{view.__name__} declares `r` but has no action_refresh method"
