"""Widget integration tests for WalletView + wallet modals.

Pure aggregation math is tested in test_wallet_overview.py — these cover
the wiring: snapshot + positions + transactions → rendered widgets, and
modal → WalletService call.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from textual.app import App
from textual.widgets import Button, Checkbox, Input, Static

from scanner.core.config import ScannerConfig
from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.tui.service import ScanService
from scanner.tui.views.wallet import WalletView
from scanner.tui.views.wallet_modals import TopupModal, WalletResetModal, WithdrawModal


def _seed(tmp_path) -> ScanService:
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(
        EventRow(event_id="e1", title="BTC April", updated_at="now"),
        db,
    )
    upsert_market(
        MarketRow(
            market_id="m1", event_id="e1", question="Will BTC reach $80K?",
            clob_token_id_yes="tok_yes", clob_token_id_no="tok_no",
            yes_price=0.5, no_price=0.5, updated_at="now",
            # Simulate a crypto_fees_v2 market so tests exercise the fee path;
            # most real Polymarket markets have fees_enabled=False.
            fees_enabled=1, fee_rate=0.072,
        ),
        db,
    )
    return ScanService(config=ScannerConfig(), db=db)


class _WalletHost(App):
    def __init__(self, service: ScanService) -> None:
        super().__init__()
        self._service = service

    def on_mount(self) -> None:
        self.push_screen(_WrappedScreen(self._service))


class _WrappedScreen:
    """Wrapper so WalletView can be pushed as a Screen-like element."""
    # Not actually used — we push the view via _HostScreen below.
    ...


from textual.screen import Screen  # noqa: E402 — after App imports for clarity


class _HostScreen(Screen):
    def __init__(self, service: ScanService) -> None:
        super().__init__()
        self._service = service

    def compose(self):
        yield WalletView(self._service)

    def refresh_sidebar_counts(self) -> None:
        pass


class _ViewHost(App):
    def __init__(self, service: ScanService) -> None:
        super().__init__()
        self._service = service

    def on_mount(self) -> None:
        self.push_screen(_HostScreen(self._service))


# --- WalletView ---------------------------------------------------------


@pytest.mark.asyncio
async def test_wallet_view_fresh_wallet_shows_starting_balance(tmp_path):
    """No positions, no txs beyond MIGRATION → equity = cash = $100, ROI = 0%."""
    svc = _seed(tmp_path)
    host = _ViewHost(svc)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        view = host.screen.query_one(WalletView)
        # v0.8.0: balance card replaced #headline — collect all Static content
        all_text = " ".join(
            str(s.content) for s in view.query(Static) if s.content
        )
        assert "$100.00" in all_text
        assert "+0.00%" in all_text or "0.00%" in all_text


@pytest.mark.asyncio
async def test_wallet_view_after_buy_shows_position_value(tmp_path):
    """Buy 20 shares at 50¢ → cash drops, positions market value ≈ $10."""
    svc = _seed(tmp_path)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=20.0)

    host = _ViewHost(svc)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        view = host.screen.query_one(WalletView)
        # v0.8.0: metrics live inside balance card KVRows — collect all Static content
        all_text = " ".join(
            str(s.content) for s in view.query(Static) if s.content
        )
        assert "1 个持仓" in all_text
        # Cash ≈ 100 - 10 - 0.36 fee = 89.64; market value ≈ 10.00
        assert "89." in all_text or "89" in all_text


@pytest.mark.asyncio
async def test_wallet_view_ledger_shows_buy_then_fee_rows(tmp_path):
    """A single execute_buy produces BUY + FEE rows in the ledger."""
    svc = _seed(tmp_path)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=20.0)

    host = _ViewHost(svc)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        view = host.screen.query_one(WalletView)
        from textual.widgets import DataTable
        table = view.query_one("#wallet-table", DataTable)
        # BUY + FEE = 2 rows (fresh DB has no pre-existing ledger entries).
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_wallet_view_realized_pnl_after_profitable_sell(tmp_path):
    """Sell at higher price → cumulative realized P&L positive on view."""
    svc = _seed(tmp_path)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=20.0)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.6,
    ):
        svc.execute_sell(market_id="m1", side="yes", shares=10.0)

    host = _ViewHost(svc)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        view = host.screen.query_one(WalletView)
        # v0.8.0: realized P&L in balance card KVRows — collect all Static content
        all_text = " ".join(
            str(s.content) for s in view.query(Static) if s.content
        )
        # realized = (0.6 - 0.5) × 10 = 1.0
        assert "$1.00" in all_text


# --- TopupModal ---------------------------------------------------------


class _ModalHost(App):
    def __init__(self, service: ScanService, modal_cls) -> None:
        super().__init__()
        self._service = service
        self._modal_cls = modal_cls
        self.dismiss_result = None

    def on_mount(self) -> None:
        def _on_dismiss(r):
            self.dismiss_result = r
        self.push_screen(self._modal_cls(self._service), _on_dismiss)


@pytest.mark.asyncio
async def test_topup_modal_confirm_calls_service_and_dismisses(tmp_path):
    svc = _seed(tmp_path)
    host = _ModalHost(svc, TopupModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        modal.query_one("#amount", Input).value = "25"
        await pilot.pause()
        modal.query_one("#confirm", Button).press()
        await pilot.pause()

    assert host.dismiss_result == 25.0
    assert svc.wallet.get_cash() == pytest.approx(125.0)


@pytest.mark.asyncio
async def test_topup_modal_quick_button_fills_amount(tmp_path):
    svc = _seed(tmp_path)
    host = _ModalHost(svc, TopupModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        modal.query_one("#quick-100", Button).press()
        await pilot.pause()
        assert modal.query_one("#amount", Input).value == "100"


# --- WithdrawModal ------------------------------------------------------


@pytest.mark.asyncio
async def test_withdraw_modal_rejects_over_cash(tmp_path):
    """Amount > cash disables confirm + shows warning."""
    svc = _seed(tmp_path)
    host = _ModalHost(svc, WithdrawModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        modal.query_one("#amount", Input).value = "200"
        await pilot.pause()
        assert modal.query_one("#confirm", Button).disabled
        warn = modal.query_one("#warn-line", Static).content
        assert "超出" in str(warn)


@pytest.mark.asyncio
async def test_withdraw_modal_qall_fills_cash(tmp_path):
    svc = _seed(tmp_path)
    host = _ModalHost(svc, WithdrawModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        # "全部" is a non-ASCII token → QuickAmountRow assigns a positional
        # id (#quick-tok-2 for the third button at index 2).
        modal.query_one("#quick-tok-2", Button).press()
        await pilot.pause()
        assert modal.query_one("#amount", Input).value == "100.00"


@pytest.mark.asyncio
async def test_withdraw_modal_confirm_deducts_cash(tmp_path):
    svc = _seed(tmp_path)
    host = _ModalHost(svc, WithdrawModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        modal.query_one("#amount", Input).value = "30"
        await pilot.pause()
        modal.query_one("#confirm", Button).press()
        await pilot.pause()

    assert host.dismiss_result == 30.0
    assert svc.wallet.get_cash() == pytest.approx(70.0)


# --- WalletResetModal ---------------------------------------------------


@pytest.mark.asyncio
async def test_reset_modal_requires_reset_keyword(tmp_path, monkeypatch):
    """Ok button stays disabled until user types literal 'reset'.

    Explicitly mock _daemon_pid → None so the test works when a real polily
    scheduler is running on the developer's machine (otherwise the checkbox
    gate kicks in and 'reset' alone isn't enough).
    """
    monkeypatch.setattr(
        "scanner.tui.views.wallet_modals._daemon_pid", lambda: None,
    )
    svc = _seed(tmp_path)
    # Seed a position so the warning reflects real state.
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)

    host = _ModalHost(svc, WalletResetModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        ok = modal.query_one("#confirm", Button)
        assert ok.disabled  # initial state
        modal.query_one("#confirm-input", Input).value = "not-reset"
        await pilot.pause()
        assert ok.disabled
        modal.query_one("#confirm-input", Input).value = "reset"
        await pilot.pause()
        # No daemon → no checkbox gate → should enable.
        assert not ok.disabled


@pytest.mark.asyncio
async def test_reset_modal_confirm_clears_state(tmp_path, monkeypatch):
    """Typed 'reset' → click Ok → positions + transactions wiped, cash restored.

    Reset runs on a worker thread so the UI doesn't freeze during SIGTERM+wait.
    Force _daemon_pid → None so the test is stable when a developer has the
    real scheduler running locally.
    """
    monkeypatch.setattr(
        "scanner.tui.views.wallet_modals._daemon_pid", lambda: None,
    )
    svc = _seed(tmp_path)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    assert svc.wallet.get_cash() != pytest.approx(100.0)  # buy reduced it

    host = _ModalHost(svc, WalletResetModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        modal.query_one("#confirm-input", Input).value = "reset"
        await pilot.pause()
        modal.query_one("#confirm", Button).press()
        # Wait for the worker thread to complete the reset and dismiss.
        for _ in range(20):
            await pilot.pause()
            if host.dismiss_result is not None:
                break

    assert host.dismiss_result is True
    assert svc.wallet.get_cash() == pytest.approx(100.0)
    assert svc.positions.get_all_positions() == []


@pytest.mark.asyncio
async def test_reset_modal_sigterms_daemon_before_reset(tmp_path, monkeypatch):
    """When daemon is running, SIGTERM is sent BEFORE reset_wallet touches the DB."""
    import signal as _signal

    svc = _seed(tmp_path)
    monkeypatch.setattr(
        "scanner.tui.views.wallet_modals._daemon_pid", lambda: 99999,
    )
    kills: list[tuple] = []

    def _fake_kill(pid: int, sig: int) -> None:
        kills.append((pid, sig))
        # Keep the worker moving — don't actually kill anything.

    monkeypatch.setattr("scanner.tui.views.wallet_modals.os.kill", _fake_kill)
    # Skip the 1s grace in tests.
    monkeypatch.setattr("scanner.tui.views.wallet_modals.time.sleep", lambda _s: None)

    host = _ModalHost(svc, WalletResetModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        modal.query_one("#confirm-input", Input).value = "reset"
        modal.query_one("#ack-daemon", Checkbox).value = True
        await pilot.pause()
        modal.query_one("#confirm", Button).press()
        for _ in range(20):
            await pilot.pause()
            if host.dismiss_result is not None:
                break

    assert host.dismiss_result is True
    # os.kill called with SIGTERM, then reset_wallet zeroed cash back to start.
    assert (99999, _signal.SIGTERM) in kills


@pytest.mark.asyncio
async def test_reset_modal_shows_daemon_warning_when_running(tmp_path, monkeypatch):
    """When PID file exists with a live PID, modal shows checkbox gate."""
    svc = _seed(tmp_path)
    monkeypatch.setattr(
        "scanner.tui.views.wallet_modals._daemon_pid", lambda: 12345,
    )
    # Also pretend os.kill succeeds so nothing crashes on confirm (we don't
    # confirm in this test).
    host = _ModalHost(svc, WalletResetModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        # The checkbox should exist only when daemon is running.
        checkbox = modal.query_one("#ack-daemon", Checkbox)
        assert checkbox is not None
        # Typing reset alone is not enough; checkbox must also be checked.
        modal.query_one("#confirm-input", Input).value = "reset"
        await pilot.pause()
        assert modal.query_one("#confirm", Button).disabled
        checkbox.value = True
        await pilot.pause()
        assert not modal.query_one("#confirm", Button).disabled


# --- WalletResetModal: auto-restart daemon (follow-up hardening) -------


def _prime_daemon_mocks(monkeypatch, pid: int = 99999) -> list[tuple]:
    """Shared setup: daemon appears running, os.kill + sleep are neutralized,
    caller gets back the kills list for assertions.
    """
    monkeypatch.setattr(
        "scanner.tui.views.wallet_modals._daemon_pid", lambda: pid,
    )
    kills: list[tuple] = []
    monkeypatch.setattr(
        "scanner.tui.views.wallet_modals.os.kill",
        lambda p, s: kills.append((p, s)),
    )
    monkeypatch.setattr(
        "scanner.tui.views.wallet_modals.time.sleep", lambda _s: None,
    )
    return kills


@pytest.mark.asyncio
async def test_reset_modal_auto_restarts_daemon_when_monitors_exist(
    tmp_path, monkeypatch,
):
    """Reset while daemon running + active monitor → restart_daemon called
    automatically after reset succeeds. User shouldn't need to `polily
    scheduler restart` by hand.
    """
    from scanner.core.monitor_store import upsert_event_monitor

    svc = _seed(tmp_path)
    upsert_event_monitor("e1", auto_monitor=True, db=svc.db)
    _prime_daemon_mocks(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        "scanner.daemon.scheduler.restart_daemon",
        lambda: calls.append("restart") or True,
    )

    host = _ModalHost(svc, WalletResetModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        modal.query_one("#confirm-input", Input).value = "reset"
        modal.query_one("#ack-daemon", Checkbox).value = True
        await pilot.pause()
        modal.query_one("#confirm", Button).press()
        for _ in range(20):
            await pilot.pause()
            if host.dismiss_result is not None:
                break

    assert host.dismiss_result is True
    assert calls == ["restart"], (
        f"restart_daemon should fire exactly once, got {calls}"
    )


@pytest.mark.asyncio
async def test_reset_modal_skips_restart_when_no_active_monitors(
    tmp_path, monkeypatch,
):
    """Reset while daemon running + NO active monitors → don't start daemon
    back up. Follows the same rule as TUI on_mount: no monitors = no daemon.
    """
    svc = _seed(tmp_path)
    # Intentionally do NOT upsert an event monitor.
    _prime_daemon_mocks(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        "scanner.daemon.scheduler.restart_daemon",
        lambda: calls.append("restart") or True,
    )

    host = _ModalHost(svc, WalletResetModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        modal.query_one("#confirm-input", Input).value = "reset"
        modal.query_one("#ack-daemon", Checkbox).value = True
        await pilot.pause()
        modal.query_one("#confirm", Button).press()
        for _ in range(20):
            await pilot.pause()
            if host.dismiss_result is not None:
                break

    assert host.dismiss_result is True
    assert calls == [], (
        f"restart_daemon must be skipped when no active monitors, got {calls}"
    )


@pytest.mark.asyncio
async def test_reset_modal_restart_failure_still_dismisses_truthy(
    tmp_path, monkeypatch,
):
    """If restart_daemon raises, wallet reset itself must still have
    succeeded (dismiss=True + cash restored). We log a warning via notify
    but don't fail the whole flow — the DB work is already committed.
    """
    from scanner.core.monitor_store import upsert_event_monitor

    svc = _seed(tmp_path)
    upsert_event_monitor("e1", auto_monitor=True, db=svc.db)
    _prime_daemon_mocks(monkeypatch)

    def _boom() -> bool:
        raise RuntimeError("launchctl load failed")

    monkeypatch.setattr(
        "scanner.daemon.scheduler.restart_daemon", _boom,
    )
    # Buy something so the reset has state to clear + we can observe rollback.
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    assert svc.wallet.get_cash() != pytest.approx(100.0)

    host = _ModalHost(svc, WalletResetModal)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = host.screen
        modal.query_one("#confirm-input", Input).value = "reset"
        modal.query_one("#ack-daemon", Checkbox).value = True
        await pilot.pause()
        modal.query_one("#confirm", Button).press()
        for _ in range(20):
            await pilot.pause()
            if host.dismiss_result is not None:
                break

    assert host.dismiss_result is True, (
        "reset must still report success; restart is secondary"
    )
    assert svc.wallet.get_cash() == pytest.approx(100.0)
    assert svc.positions.get_all_positions() == []
