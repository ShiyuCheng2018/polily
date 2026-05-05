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

from polily.tui.i18n import t
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
        Binding("q", "quit_app", "Quit"),
        Binding("ctrl+c", "quit_app", "Quit"),
    ]

    def __init__(self, *, error_message: str) -> None:
        super().__init__()
        self._error = error_message

    def compose(self) -> ComposeResult:
        # SF18 — Pydantic ValidationError messages contain `[type=...]`
        # bracket syntax that Rich tries to parse as markup, raising
        # MarkupError on Static.update / render. The modal already
        # escapes via rich.markup.escape (config_modals.py:160) — same
        # fix here so the fatal screen survives any real validation
        # message it's handed.
        from rich.markup import escape as _escape_markup

        with Vertical(id="fatal-box"):
            with PolilyZone(title=t("fatal_config.zone_title", icon=ICON_CONFIG)):
                yield Static(t("fatal_config.intro"))
                yield Static(_escape_markup(str(self._error)), id="error-text")
                yield Static(t("fatal_config.recovery_intro"))
                yield Static(t("fatal_config.recovery_all"))
                yield Static("$ polily config reset --all", classes="recovery-cmd")
                yield Static(t("fatal_config.recovery_one"))
                yield Static(
                    "$ polily config reset <key_path>",
                    classes="recovery-cmd",
                )
                yield Static(t("fatal_config.exit_hint"))

    def action_quit_app(self) -> None:
        import os

        from polily.tui.terminal_cleanup import cleanup_terminal
        # R5-B: clean mouse-tracking + alt-screen before bypassing
        # Textual's atexit handlers via os._exit. self.app._driver is
        # the canonical path; cleanup_terminal handles missing-driver
        # gracefully via fallback DECRST writes.
        cleanup_terminal(self.app)
        os._exit(1)
