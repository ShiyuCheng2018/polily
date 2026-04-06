"""Polily TUI — interactive terminal interface (Textual)."""

from textual.app import App
from textual.binding import Binding

from scanner.tui.screens.main import MainScreen
from scanner.tui.service import ScanService


class PolilyApp(App):
    """Polily Decision Copilot — interactive terminal UI."""

    TITLE = "Polily"
    SUB_TITLE = "Polymarket Decision Copilot"
    CSS_PATH = "css/app.tcss"

    BINDINGS = [
        Binding("q", "quit", "退出"),
    ]

    def __init__(self):
        super().__init__()
        self.service = ScanService()

    def on_mount(self) -> None:
        self._ensure_daemon()
        self.push_screen(MainScreen(self.service))

    def _ensure_daemon(self) -> None:
        """Auto-start scheduler daemon if not running and there are auto-monitored markets."""
        from scanner.market_state import get_auto_monitor_watches
        watches = get_auto_monitor_watches(self.service.db)
        if not watches:
            return
        try:
            from scanner.watch_scheduler import ensure_daemon_running
            if ensure_daemon_running():
                self.notify("后台监控已自动启动")
        except Exception:
            pass  # non-fatal — daemon can be started manually

    async def action_quit(self) -> None:
        """Kill everything and exit immediately."""
        self.exit()


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
