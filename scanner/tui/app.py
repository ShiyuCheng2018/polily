"""Polily TUI — interactive terminal interface (Textual)."""

from textual.app import App

from scanner.tui.bindings import GLOBAL_BINDINGS
from scanner.tui.screens.main import MainScreen
from scanner.tui.service import ScanService
from scanner.tui.theme import register_polily_theme


class PolilyApp(App):
    """Polily — A Polymarket Monitoring Agent That Actually Works (interactive TUI)."""

    TITLE = "Polily"
    SUB_TITLE = "A Polymarket Monitoring Agent That Actually Works"
    CSS_PATH = ["css/tokens.tcss", "css/app.tcss"]

    BINDINGS = GLOBAL_BINDINGS

    def __init__(self, service: ScanService | None = None):
        super().__init__()
        self.service = service or ScanService()

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
        from scanner.core.monitor_store import get_active_monitors
        monitors = get_active_monitors(self.service.db)
        if not monitors:
            return
        try:
            from scanner.daemon.scheduler import restart_daemon
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
