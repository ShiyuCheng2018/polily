"""Polily TUI — interactive terminal interface (Textual)."""

import logging
from pathlib import Path

from textual.app import App

from polily.core.events import TOPIC_LANGUAGE_CHANGED, get_event_bus
from polily.core.user_prefs import get_pref, set_pref
from polily.tui import i18n
from polily.tui.bindings import GLOBAL_BINDINGS
from polily.tui.screens.main import MainScreen
from polily.tui.service import PolilyService
from polily.tui.theme import register_polily_theme

logger = logging.getLogger(__name__)


class PolilyApp(App):
    """Polily — A Polymarket Monitoring Agent That Actually Works (interactive TUI)."""

    TITLE = "Polily"
    SUB_TITLE = "A Polymarket Monitoring Agent That Actually Works"
    CSS_PATH = ["css/tokens.tcss", "css/app.tcss"]

    BINDINGS = GLOBAL_BINDINGS

    def __init__(self, service: PolilyService | None = None):
        super().__init__()
        self.service = service or PolilyService()
        self._init_i18n_from_prefs()

    def _init_i18n_from_prefs(self) -> None:
        """Resolve startup language: DB user_prefs.language > config.tui.language > "zh".

        Loaded once during __init__ (before any view composes) so the very first
        render already sees translated strings — no flash of zh during startup
        when the user previously chose en.
        """
        catalogs_dir = Path(i18n.__file__).parent / "catalogs"
        catalogs = i18n.load_catalogs(catalogs_dir)
        configured = self.service.config.tui.language
        stored = get_pref(self.service.db, "language", default=configured)
        if stored not in catalogs:
            logger.warning("i18n: stored language %r not in catalogs (%s); falling back to %r",
                           stored, sorted(catalogs), configured)
            stored = configured
        i18n.init_i18n(catalogs, default=stored)

    def on_mount(self) -> None:
        register_polily_theme(self)  # NEW: register brand theme
        self._restart_daemon()
        self.push_screen(MainScreen(self.service))

    def _restart_daemon(self) -> None:
        """Restart scheduler daemon on every TUI launch.

        Previously only started the daemon if it wasn't already running. Now
        we always restart (when there are auto-monitored events) so the
        daemon picks up the latest code the user has committed. New daemon
        writes a fresh `data/logs/poll-v<ver>-<ts>.log`; old logs are kept.
        """
        from polily.core.monitor_store import get_active_monitors
        monitors = get_active_monitors(self.service.db)
        if not monitors:
            return
        try:
            from polily.daemon.scheduler import restart_daemon
            if restart_daemon():
                self.notify("后台监控已重启 (已加载最新代码)")
        except Exception:
            pass  # non-fatal — daemon can be started manually

    async def action_quit(self) -> None:
        """Kill everything and exit immediately."""
        self.exit()

    async def action_back(self) -> None:
        """Pop current screen if any; else no-op."""
        if len(self.screen_stack) > 1:
            self.pop_screen()

    async def action_help(self) -> None:
        """Placeholder for help overlay — Phase 3 actual overlay widget.
        For now, notify."""
        self.notify("帮助面板 v0.8.0 后续版本提供", severity="information")

    async def action_toggle_language(self) -> None:
        """Cycle through available languages, persist to DB, broadcast change.

        I18nFooter (every screen on stack) re-composes via TOPIC_LANGUAGE_CHANGED
        subscription. Views that mix i18n strings into their own widgets must
        also subscribe to the same topic and call recompose=True (see wallet.py
        for the canonical pattern).
        """
        langs = i18n.available_languages()
        if not langs:
            return
        try:
            idx = langs.index(i18n.current_language())
        except ValueError:
            idx = -1
        next_lang = langs[(idx + 1) % len(langs)]
        i18n.set_language(next_lang)
        set_pref(self.service.db, "language", next_lang)
        get_event_bus().publish(TOPIC_LANGUAGE_CHANGED, {"language": next_lang})


def run_tui():
    """Entry point for TUI mode."""
    app = PolilyApp()
    try:
        app.run()
    finally:
        # Force-kill all child processes and exit immediately.
        # claude CLI (used by AI agents) spawns Node.js subprocesses that
        # survive normal Python shutdown (sys.exit, atexit). os._exit bypasses
        # all cleanup but is the only reliable way to terminate. SQLite writes
        # are committed before reaching this point. See README Limitations.
        import os
        os._exit(0)
