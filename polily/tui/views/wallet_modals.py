"""Modals for the Wallet page: Topup / Withdraw / WalletReset.

All three dismiss with a truthy payload on success (parent refreshes) and
None on cancel. Topup/Withdraw call WalletService directly; Reset stops
the daemon first (if running) then calls reset_wallet.

v0.8.0 migration:
- Topup / Withdraw wrap inputs in PolilyCard (ICON_BUY / ICON_SELL titles)
- WalletResetModal wraps destructive-confirm flow in PolilyZone (ICON_SETTINGS)
- Quick-amount rows replaced by QuickAmountRow atom (Opt-A2): button ids
  moved from #q50/#q100/#q500, #q20/#q50/#qall → #quick-50/#quick-100/...,
  #quick-20/#quick-50/#quick-tok-2 (non-ASCII token "全部"). Other widget
  IDs preserved (#amount, #confirm, #cancel, #confirm-input, #ack-daemon,
  #warn-line).
- push_screen / dismiss protocol untouched
"""

from __future__ import annotations

import os
import signal
import time

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Static

from polily.tui.icons import ICON_BUY, ICON_SELL, ICON_SETTINGS, ICON_WALLET
from polily.tui.widgets.amount_input import AmountInput
from polily.tui.widgets.confirm_cancel_bar import ConfirmCancelBar
from polily.tui.widgets.field_row import FieldRow
from polily.tui.widgets.polily_card import PolilyCard
from polily.tui.widgets.polily_zone import PolilyZone
from polily.tui.widgets.quick_amount_row import QuickAmountRow

_MODAL_WIDTH = 62


def _daemon_pid() -> int | None:
    """Return live daemon PID or None via launchctl.

    v0.9.0: previously stat'd `data/scheduler.pid`. Now routed through
    `launchctl_query` for consistency with the rest of the TUI.
    """
    from polily.daemon.launchctl_query import get_daemon_pid
    return get_daemon_pid()


# --- Topup ----------------------------------------------------------------


class TopupModal(ModalScreen[float | None]):
    """Amount input + quick-amount buttons. On confirm → WalletService.topup."""

    DEFAULT_CSS = f"""
    TopupModal {{
        align: center middle;
    }}
    TopupModal #dialog-box {{
        width: {_MODAL_WIDTH};
        height: auto;
    }}
    TopupModal > #dialog-box > PolilyCard {{
        height: auto;
        margin: 0;
    }}
    TopupModal #amount {{ width: 14; }}
    TopupModal QuickAmountRow {{ padding: 0 0 1 0; }}
    TopupModal QuickAmountRow Button {{ min-width: 7; }}
    TopupModal ConfirmCancelBar Button {{ min-width: 14; }}
    """
    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, service) -> None:
        super().__init__()
        self._service = service

    def compose(self) -> ComposeResult:
        cash = self._service.wallet.get_cash()
        with Vertical(id="dialog-box"):
            with PolilyCard(title=f"{ICON_BUY} 充值"):
                yield Static(
                    f"{ICON_WALLET} 当前余额: ${cash:.2f}",
                    classes="balance-line pb-sm text-muted",
                )
                yield FieldRow(
                    label="金额",
                    unit="$",
                    input_widget=AmountInput(value="50", id="amount"),
                )
                yield QuickAmountRow(amounts=[50, 100, 500])
                yield ConfirmCancelBar()

    def on_quick_amount_row_selected(
        self, event: QuickAmountRow.Selected,
    ) -> None:
        self.query_one("#amount", Input).value = str(event.amount)

    def on_confirm_cancel_bar_confirmed(
        self, event: ConfirmCancelBar.Confirmed,
    ) -> None:
        self._confirm()

    def on_confirm_cancel_bar_cancelled(
        self, event: ConfirmCancelBar.Cancelled,
    ) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _confirm(self) -> None:
        amt, valid, _ = self.query_one("#amount", AmountInput).parse()
        if not valid or amt is None:
            self.notify("请输入有效金额 (> 0)", severity="error")
            return
        try:
            self._service.topup(amt)
        except Exception as e:
            self.notify(f"充值失败: {e}", severity="error")
            return
        self.notify(f"充值成功: +${amt:.2f}")
        self.dismiss(amt)


# --- Withdraw -------------------------------------------------------------


class WithdrawModal(ModalScreen[float | None]):
    """Amount input + max-cash guard. On confirm → WalletService.withdraw."""

    DEFAULT_CSS = f"""
    WithdrawModal {{
        align: center middle;
    }}
    WithdrawModal #dialog-box {{
        width: {_MODAL_WIDTH};
        height: auto;
    }}
    WithdrawModal > #dialog-box > PolilyCard {{
        height: auto;
        margin: 0;
    }}
    WithdrawModal #amount {{ width: 14; }}
    WithdrawModal QuickAmountRow {{ padding: 0 0 1 0; }}
    WithdrawModal QuickAmountRow Button {{ min-width: 7; }}
    WithdrawModal #warn-line {{ padding: 0 0 1 0; }}
    WithdrawModal ConfirmCancelBar Button {{ min-width: 14; }}
    """
    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, service) -> None:
        super().__init__()
        self._service = service
        self._cash = service.wallet.get_cash()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-box"):
            with PolilyCard(title=f"{ICON_SELL} 提现"):
                yield Static(
                    f"{ICON_WALLET} 可提现 (现金): ${self._cash:.2f}",
                    classes="balance-line text-muted",
                )
                yield Static(
                    "[dim]持仓市值不可提现[/dim]",
                    classes="hint pb-sm text-muted",
                )
                yield FieldRow(
                    label="金额",
                    unit="$",
                    input_widget=AmountInput(
                        value="", id="amount", max_value=self._cash,
                    ),
                )
                yield QuickAmountRow(amounts=[20, 50, "全部"])
                yield Static("", id="warn-line")
                yield ConfirmCancelBar()

    def on_mount(self) -> None:
        # Empty input on open → confirm must start disabled.
        self._refresh_warn()

    def on_amount_input_amount_changed(
        self, event: AmountInput.AmountChanged,
    ) -> None:
        if event.input_id == "amount":
            self._refresh_warn()

    def on_quick_amount_row_selected(
        self, event: QuickAmountRow.Selected,
    ) -> None:
        if event.amount == "全部":
            # Resolve the "max available" token against current cash.
            self.query_one("#amount", Input).value = f"{self._cash:.2f}"
        else:
            self.query_one("#amount", Input).value = str(event.amount)

    def on_confirm_cancel_bar_confirmed(
        self, event: ConfirmCancelBar.Confirmed,
    ) -> None:
        self._confirm()

    def on_confirm_cancel_bar_cancelled(
        self, event: ConfirmCancelBar.Cancelled,
    ) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _parse(self) -> tuple[float | None, bool, str]:
        return self.query_one("#amount", AmountInput).parse()

    def _refresh_warn(self) -> None:
        warn = self.query_one("#warn-line", Static)
        ok_btn = self.query_one("#confirm", Button)
        amt, valid, reason = self._parse()
        if valid:
            warn.update("")
            ok_btn.disabled = False
            return
        if reason == "above_max":
            warn.update(f"[red]超出可提金额[/red] (最多 ${self._cash:.2f})")
        else:
            warn.update("")
        ok_btn.disabled = True

    def _confirm(self) -> None:
        amt, valid, _ = self._parse()
        if not valid or amt is None:
            return
        try:
            self._service.withdraw(amt)
        except Exception as e:
            self.notify(f"提现失败: {e}", severity="error")
            return
        self.notify(f"提现成功: -${amt:.2f}")
        self.dismiss(amt)


# --- Reset ----------------------------------------------------------------


class WalletResetModal(ModalScreen[bool | None]):
    """Hard reset: stops daemon first (if running) then clears positions +
    transactions and resets cash to starting_balance.

    Two-gate confirmation: user must type literal "reset" and (if daemon
    running) tick the "I know daemon will stop" checkbox.
    """

    DEFAULT_CSS = """
    WalletResetModal {
        align: center middle;
    }
    WalletResetModal #dialog-box {
        width: 68;
        height: auto;
    }
    WalletResetModal > #dialog-box > PolilyZone {
        height: auto;
        margin: 0;
        border: round $error;
    }
    WalletResetModal .polily-zone-title { color: $error; }
    WalletResetModal #confirm-prompt { padding: 0 0 0 0; }
    WalletResetModal #confirm-input { width: 20; }
    WalletResetModal ConfirmCancelBar Button { min-width: 14; }
    """
    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, service) -> None:
        super().__init__()
        self._service = service
        self._daemon_pid = _daemon_pid()
        self._open_positions = len(service.positions.get_all_positions())

    def compose(self) -> ComposeResult:
        starting = self._service.config.wallet.starting_balance
        with Vertical(id="dialog-box"):
            with PolilyZone(title=f"{ICON_SETTINGS} 重置钱包"):
                warn_lines = [
                    "[b red]⚠  不可撤销！将清除：[/b red]",
                    f"    · 所有持仓 (当前 {self._open_positions} 个)",
                    "    · 所有交易流水",
                    f"    · 现金重置为初始 ${starting:.2f}",
                ]
                yield Static("\n".join(warn_lines), classes="warn-block pb-sm")
                if self._daemon_pid is not None:
                    daemon_text = (
                        f"⚠  后台监控正在运行 (PID {self._daemon_pid})\n"
                        "    重置会先停止 daemon。完成后请手动执行：\n"
                        "        polily scheduler restart"
                    )
                    yield Static(
                        daemon_text,
                        classes="daemon-block pb-sm text-warning",
                    )
                    yield Checkbox("我知道 daemon 会被停止", id="ack-daemon")
                yield Static('确认请输入 [bold]reset[/bold] :', id="confirm-prompt")
                yield Input(value="", id="confirm-input")
                yield ConfirmCancelBar(
                    confirm_label="重置",
                    cancel_label="取消",
                    destructive=True,
                )

    def on_mount(self) -> None:
        # Gate starts locked; _refresh_ok_state enables it once typed "reset"
        # (and daemon-ack if needed).
        self.query_one("#confirm", Button).disabled = True

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh_ok_state()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._refresh_ok_state()

    def on_confirm_cancel_bar_confirmed(
        self, event: ConfirmCancelBar.Confirmed,
    ) -> None:
        self._confirm()

    def on_confirm_cancel_bar_cancelled(
        self, event: ConfirmCancelBar.Cancelled,
    ) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _typed_reset(self) -> bool:
        return self.query_one("#confirm-input", Input).value.strip() == "reset"

    def _ack_daemon(self) -> bool:
        if self._daemon_pid is None:
            return True
        try:
            return bool(self.query_one("#ack-daemon", Checkbox).value)
        except Exception:
            return False

    def _refresh_ok_state(self) -> None:
        self.query_one("#confirm", Button).disabled = not (
            self._typed_reset() and self._ack_daemon()
        )

    def _confirm(self) -> None:
        if not (self._typed_reset() and self._ack_daemon()):
            return
        # Disable inputs while the worker runs so the user can't double-click.
        self.query_one("#confirm", Button).disabled = True
        self.query_one("#cancel", Button).disabled = True
        self.run_worker(self._do_reset, thread=True, exclusive=True)

    def _do_reset(self) -> None:
        """Worker thread: SIGTERM + 1s grace + reset. Keeps UI responsive."""
        if self._daemon_pid is not None:
            try:
                os.kill(self._daemon_pid, signal.SIGTERM)
                time.sleep(1.0)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        from polily.core.wallet_reset import reset_wallet
        try:
            reset_wallet(
                self._service.db,
                starting_balance=self._service.config.wallet.starting_balance,
            )
        except Exception as e:
            self.app.call_from_thread(self._on_reset_failed, str(e))
            return

        # Auto-restart daemon after a clean reset so the user doesn't need
        # to `polily scheduler restart` by hand. Mirror TUI on_mount rule:
        # skip restart if no active monitors (nothing to watch anyway).
        # Restart failure must NOT fail the whole flow — the DB reset is
        # already committed; surface a warning via _on_reset_done.
        restart_err: str | None = None
        if self._daemon_pid is not None:
            from polily.core.monitor_store import get_active_monitors
            if get_active_monitors(self._service.db):
                try:
                    from polily.daemon import scheduler as _sched
                    _sched.restart_daemon()
                except Exception as e:
                    restart_err = str(e)

        self.app.call_from_thread(self._on_reset_done, restart_err)

    def _on_reset_done(self, restart_err: str | None = None) -> None:
        if restart_err is not None:
            # Reset committed, but auto-restart failed. User still needs to
            # know a manual restart is required.
            self.notify(
                f"钱包已重置。daemon 自动重启失败: {restart_err}\n"
                "请手动执行 polily scheduler restart",
                severity="warning",
            )
        elif self._daemon_pid is not None:
            self.notify("钱包已重置。后台监控已自动重启。")
        else:
            self.notify("钱包已重置。")
        self.dismiss(True)

    def _on_reset_failed(self, err: str) -> None:
        self.notify(f"重置失败: {err}", severity="error")
        self.query_one("#confirm", Button).disabled = False
        self.query_one("#cancel", Button).disabled = False
