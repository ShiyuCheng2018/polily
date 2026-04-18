"""Modals for the Wallet page: Topup / Withdraw / WalletReset.

All three dismiss with a truthy payload on success (parent refreshes) and
None on cancel. Topup/Withdraw call WalletService directly; Reset stops
the daemon first (if running) then calls reset_wallet.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static

_MODAL_WIDTH = 62


def _daemon_pid() -> int | None:
    """Return live daemon PID or None. Mirrors MainScreen._is_daemon_alive."""
    pid_path = Path("data/scheduler.pid")
    if not pid_path.exists():
        return None
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, 0)
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return None
    return pid


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
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }}
    TopupModal .title {{ text-style: bold; padding: 0 0 1 0; }}
    TopupModal .balance-line {{ padding: 0 0 1 0; color: $text-muted; }}
    TopupModal .amount-row {{ height: auto; padding: 0 0 1 0; }}
    TopupModal #amount {{ width: 14; }}
    TopupModal #quick-row {{ height: auto; padding: 0 0 1 0; }}
    TopupModal .quick-btn {{ min-width: 7; margin: 0 1 0 0; }}
    TopupModal #btn-row {{ height: auto; align: center middle; padding: 1 0 0 0; }}
    TopupModal .action-btn {{ min-width: 14; margin: 0 1; }}
    """
    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, service) -> None:
        super().__init__()
        self._service = service

    def compose(self) -> ComposeResult:
        cash = self._service.wallet.get_cash()
        with Vertical(id="dialog-box"):
            yield Static("充值", classes="title")
            yield Static(f"当前余额: ${cash:.2f}", classes="balance-line")
            with Horizontal(classes="amount-row"):
                yield Label("金额 $", classes="field-label")
                yield Input(value="50", id="amount", type="number")
            with Horizontal(id="quick-row"):
                yield Label("快捷", classes="field-label")
                for amt in (50, 100, 500):
                    yield Button(f"${amt}", id=f"q{amt}", classes="quick-btn")
            with Horizontal(id="btn-row"):
                yield Button("确认", id="ok", variant="primary", classes="action-btn")
                yield Button("取消", id="cancel", classes="action-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id is None:
            return
        if event.button.id.startswith("q"):
            self.query_one("#amount", Input).value = event.button.id[1:]
            return
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "ok":
            self._confirm()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _confirm(self) -> None:
        try:
            amt = float(self.query_one("#amount", Input).value)
        except (ValueError, TypeError):
            self.notify("请输入有效金额", severity="error")
            return
        if amt <= 0:
            self.notify("金额必须大于 0", severity="error")
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
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }}
    WithdrawModal .title {{ text-style: bold; padding: 0 0 1 0; }}
    WithdrawModal .balance-line {{ padding: 0 0 0 0; color: $text-muted; }}
    WithdrawModal .hint {{ padding: 0 0 1 0; color: $text-muted; }}
    WithdrawModal .amount-row {{ height: auto; padding: 0 0 1 0; }}
    WithdrawModal #amount {{ width: 14; }}
    WithdrawModal #quick-row {{ height: auto; padding: 0 0 1 0; }}
    WithdrawModal .quick-btn {{ min-width: 7; margin: 0 1 0 0; }}
    WithdrawModal #warn-line {{ padding: 0 0 1 0; }}
    WithdrawModal #btn-row {{ height: auto; align: center middle; padding: 1 0 0 0; }}
    WithdrawModal .action-btn {{ min-width: 14; margin: 0 1; }}
    """
    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, service) -> None:
        super().__init__()
        self._service = service
        self._cash = service.wallet.get_cash()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-box"):
            yield Static("提现", classes="title")
            yield Static(f"可提现 (现金): ${self._cash:.2f}", classes="balance-line")
            yield Static("[dim]持仓市值不可提现[/dim]", classes="hint")
            with Horizontal(classes="amount-row"):
                yield Label("金额 $", classes="field-label")
                yield Input(value="", id="amount", type="number")
            with Horizontal(id="quick-row"):
                yield Label("快捷", classes="field-label")
                yield Button("$20", id="q20", classes="quick-btn")
                yield Button("$50", id="q50", classes="quick-btn")
                yield Button("全部", id="qall", classes="quick-btn")
            yield Static("", id="warn-line")
            with Horizontal(id="btn-row"):
                yield Button("确认", id="ok", variant="primary", classes="action-btn")
                yield Button("取消", id="cancel", classes="action-btn")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh_warn()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id is None:
            return
        if event.button.id.startswith("q"):
            if event.button.id == "qall":
                self.query_one("#amount", Input).value = f"{self._cash:.2f}"
            else:
                self.query_one("#amount", Input).value = event.button.id[1:]
            return
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "ok":
            self._confirm()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _parse(self) -> float | None:
        try:
            v = float(self.query_one("#amount", Input).value)
            return v if v > 0 else None
        except (ValueError, TypeError):
            return None

    def _refresh_warn(self) -> None:
        warn = self.query_one("#warn-line", Static)
        ok_btn = self.query_one("#ok", Button)
        amt = self._parse()
        if amt is None:
            warn.update("")
            ok_btn.disabled = True
            return
        if amt > self._cash:
            warn.update(f"[red]超出可提金额[/red] (最多 ${self._cash:.2f})")
            ok_btn.disabled = True
            return
        warn.update("")
        ok_btn.disabled = False

    def _confirm(self) -> None:
        amt = self._parse()
        if amt is None or amt > self._cash:
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
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    WalletResetModal .title { text-style: bold; color: $error; padding: 0 0 1 0; }
    WalletResetModal .warn-block { padding: 0 0 1 0; }
    WalletResetModal .daemon-block { padding: 0 0 1 0; color: $warning; }
    WalletResetModal #confirm-prompt { padding: 0 0 0 0; }
    WalletResetModal #confirm-input { width: 20; }
    WalletResetModal #btn-row { height: auto; align: center middle; padding: 1 0 0 0; }
    WalletResetModal .action-btn { min-width: 14; margin: 0 1; }
    """
    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, service) -> None:
        super().__init__()
        self._service = service
        self._daemon_pid = _daemon_pid()
        self._open_positions = len(service.positions.get_all_positions())

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-box"):
            yield Static("重置钱包", classes="title")
            warn_lines = [
                "⚠️  不可撤销！将清除：",
                f"    · 所有持仓 (当前 {self._open_positions} 个)",
                "    · 所有交易流水",
                "    · 现金重置为初始 $100",
            ]
            yield Static("\n".join(warn_lines), classes="warn-block")
            if self._daemon_pid is not None:
                daemon_text = (
                    f"⚠️  后台监控正在运行 (PID {self._daemon_pid})\n"
                    "    重置会先停止 daemon。完成后请手动执行：\n"
                    "        polily scheduler restart"
                )
                yield Static(daemon_text, classes="daemon-block")
                yield Checkbox("我知道 daemon 会被停止", id="ack-daemon")
            yield Static('确认请输入 [bold]reset[/bold] :', id="confirm-prompt")
            yield Input(value="", id="confirm-input")
            with Horizontal(id="btn-row"):
                yield Button("重置", id="ok", variant="error", classes="action-btn", disabled=True)
                yield Button("取消", id="cancel", classes="action-btn")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh_ok_state()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._refresh_ok_state()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "ok":
            self._confirm()

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
        self.query_one("#ok", Button).disabled = not (
            self._typed_reset() and self._ack_daemon()
        )

    def _confirm(self) -> None:
        if not (self._typed_reset() and self._ack_daemon()):
            return
        # Disable inputs while the worker runs so the user can't double-click.
        self.query_one("#ok", Button).disabled = True
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
        from scanner.core.wallet_reset import reset_wallet
        try:
            reset_wallet(
                self._service.db,
                starting_balance=self._service.config.wallet.starting_balance,
            )
        except Exception as e:
            self.app.call_from_thread(self._on_reset_failed, str(e))
            return
        self.app.call_from_thread(self._on_reset_done)

    def _on_reset_done(self) -> None:
        if self._daemon_pid is not None:
            self.notify(
                "钱包已重置。daemon 已停止，请手动 polily scheduler restart 重新启用监控。",
            )
        else:
            self.notify("钱包已重置。")
        self.dismiss(True)

    def _on_reset_failed(self, err: str) -> None:
        self.notify(f"重置失败: {err}", severity="error")
        self.query_one("#ok", Button).disabled = False
        self.query_one("#cancel", Button).disabled = False
