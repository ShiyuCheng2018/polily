"""Polily TUI — interactive terminal interface (Textual)."""

from textual.app import App
from textual.binding import Binding

from scanner.tui.screens.main import MainScreen
from scanner.tui.service import ScanService


class PolilyApp(App):
    """Polily Decision Copilot — interactive terminal UI."""

    TITLE = "Polily"
    SUB_TITLE = "Polymarket Decision Copilot"
    CSS_PATH = ["css/tokens.tcss", "css/app.tcss"]

    BINDINGS = [
        Binding("q", "quit", "退出"),
    ]

    def __init__(self, service: ScanService | None = None):
        super().__init__()
        self.service = service or ScanService()

    def on_mount(self) -> None:
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
