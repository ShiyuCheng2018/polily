"""Fatal screen shown when load_config_from_db raises ConfigValidationError.

Per design §7.3. Cannot be dismissed — user must run a CLI escape hatch
(polily config reset --all / <key>) and relaunch.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from polily.tui.icons import ICON_CONFIG
from polily.tui.widgets.polily_zone import PolilyZone


class FatalConfigScreen(Screen):
    """Modal-style screen that blocks all interaction except quit."""

    DEFAULT_CSS = """
    FatalConfigScreen {
        align: center middle;
        background: $surface;
    }
    FatalConfigScreen #fatal-box {
        width: 80;
        height: auto;
    }
    FatalConfigScreen #error-text {
        color: $error;
        padding: 1 0;
    }
    FatalConfigScreen .recovery-cmd {
        color: $primary;
        padding: 0 0 1 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit_app", "退出"),
        Binding("ctrl+c", "quit_app", "退出"),
    ]

    def __init__(self, *, error_message: str) -> None:
        super().__init__()
        self._error = error_message

    def compose(self) -> ComposeResult:
        with Vertical(id="fatal-box"):
            with PolilyZone(title=f"{ICON_CONFIG} ⚠ 配置损坏 — polily 无法启动"):
                yield Static(
                    "数据库 config 表含有非法值，Pydantic 验证失败：",
                )
                yield Static(self._error, id="error-text")
                yield Static("修复选项：")
                yield Static(
                    "1. 重置所有配置为默认（不可逆）：",
                )
                yield Static("$ polily config reset --all", classes="recovery-cmd")
                yield Static(
                    "2. 重置某一项配置为默认：",
                )
                yield Static(
                    "$ polily config reset <key_path>",
                    classes="recovery-cmd",
                )
                yield Static(
                    "[dim](按 Q 或 Ctrl+C 退出 polily)[/dim]",
                )

    def action_quit_app(self) -> None:
        import os
        os._exit(1)
