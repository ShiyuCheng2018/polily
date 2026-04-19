"""MainScreen: Sidebar navigation + Content area with view switching."""


from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from scanner.tui.service import AnalysisInProgressError, ScanService
from scanner.tui.views.archived_events import ArchivedEventsView, ViewArchivedDetail
from scanner.tui.views.market_detail import (
    AnalyzeRequested,
    BackToList,
    CancelAnalysisRequested,
    MarketDetailView,
    RescoreEventRequested,
    SwitchVersionRequested,
)
from scanner.tui.views.monitor_list import MonitorListView, ViewMonitorDetail
from scanner.tui.views.paper_status import PaperStatusView, ViewTradeDetail
from scanner.tui.views.scan_log import (
    AddEventRequested,
    BackToScanLog,
    CancelScanRequested,
    OpenMarketFromLog,
    RescoreRequested,
    ScanLogDetailView,
    ScanLogView,
    StepInfo,
    ViewScanLogDetail,
)
from scanner.tui.views.score_result import (
    AddToMonitorRequested,
    BackToTasks,
    ScoreResultView,
    ScoreViewRescore,
)
from scanner.tui.widgets.sidebar import MenuSelected, Sidebar


class MainScreen(Screen):
    """Main screen with sidebar navigation and content area."""

    BINDINGS = [
        Binding("0", "show_tasks", show=False),
        Binding("r", "refresh", show=False),
        Binding("1", "show_monitor", show=False),
        Binding("2", "show_paper", show=False),
        Binding("3", "show_wallet", show=False),
        Binding("4", "show_history", show=False),
        Binding("5", "show_archive", show=False),
        Binding("up", "menu_prev", show=False),
        Binding("down", "menu_next", show=False),
    ]

    MENU_ORDER = ["tasks", "monitor", "paper", "wallet", "history", "archive"]

    def __init__(self, service: ScanService):
        super().__init__()
        self.service = service
        self._loading = False
        self._current_menu = "tasks"
        self._analyzing_event_id: str | None = None
        self._analyzing = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("就绪", id="status-bar")
        with Horizontal(id="main-container"):
            yield Sidebar(id="sidebar")
            with Vertical(id="content-area"):
                yield ScanLogView(self.service.get_scan_logs())
        yield Footer()

    def on_mount(self) -> None:
        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.set_active_menu("tasks")
        monitor = self.service.get_monitor_count()
        paper = len(self.service.get_open_trades())
        archive_count = len(self.service.get_archived_events())
        history = self.service.get_history_count()
        sidebar.update_counts(monitor, paper, archive_count, history)
        # Poll heartbeat: check every 5s
        self.set_interval(5, self._check_poll_heartbeat)
        self._check_poll_heartbeat()

    def _check_poll_heartbeat(self) -> None:
        """Check if poll daemon process is alive via PID file."""
        try:
            alive = self._is_daemon_alive()
            self.query_one("#sidebar", Sidebar).set_poll_status(alive)

            if alive and not self._loading and not self._analyzing:
                self._refresh_current_view()
        except Exception:
            import logging
            logging.getLogger(__name__).debug("heartbeat error", exc_info=True)

    @staticmethod
    def _is_daemon_alive() -> bool:
        """Check if daemon process is running via PID file."""
        import os
        from pathlib import Path
        pid_path = Path("data/scheduler.pid")
        if not pid_path.exists():
            return False
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)  # signal 0 = check if process exists
            return True
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            return False

    def _refresh_current_view(self) -> None:
        """Call refresh_data() on the current visible view if it supports it."""
        content = self.query_one("#content-area")
        # Walk all descendants, not just direct children
        for widget in content.walk_children():
            if hasattr(widget, "refresh_data"):
                widget.refresh_data()
                return

    def _update_progress(self, steps: list[StepInfo]):
        """Main thread: update live progress if ScanLogView is visible."""
        try:
            log_view = self.query_one("#content-area").query_one(ScanLogView)
            log_view.update_live_progress(steps)
        except Exception:
            pass
        if steps:
            latest = steps[-1]
            if latest.status == "running":
                self.query_one("#status-bar", Static).update(f"{latest.name}...")

    # --- Add event by URL ---

    def on_add_event_requested(self, message: AddEventRequested) -> None:
        if self._loading:
            return
        self._loading = True
        self._add_url = message.url
        self.query_one("#status-bar", Static).update("获取事件...")
        if self._current_menu == "tasks":
            self._navigate_to("tasks")
        self.run_worker(self._do_add_event, name="add_event", thread=True, exclusive=True)

    async def _do_add_event(self):
        self.service.on_progress = lambda steps: self.app.call_from_thread(
            self._update_progress, steps
        )
        try:
            result = await self.service.add_event_by_url(self._add_url)
        except Exception as e:
            self.app.call_from_thread(self._on_add_failed, str(e))
            return
        if result is None:
            self.app.call_from_thread(self._on_add_failed, "事件未找到或链接无效")
            return
        self.app.call_from_thread(self._on_add_complete, result)

    def _on_add_complete(self, result):
        self._loading = False
        event = result["event"]
        score = result["event_score"].total
        self.query_one("#status-bar", Static).update(
            f"评分完成: {event.title[:30]} ({score:.0f}分)"
        )
        self._switch_view(
            ScoreResultView(event_id=event.event_id, service=self.service)
        )
        self.refresh_sidebar_counts()

    def _on_add_failed(self, error: str):
        self._loading = False
        self.query_one("#status-bar", Static).update(f"添加失败: {error[:60]}")
        if self._current_menu == "tasks":
            self._navigate_to("tasks")

    def _switch_view(self, view, menu_id: str = ""):
        content = self.query_one("#content-area")
        for child in list(content.children):
            child.remove()
        content.mount(view)
        self.set_timer(0.1, lambda: self._focus_table(view))
        if menu_id:
            sidebar = self.query_one("#sidebar", Sidebar)
            sidebar.set_active_menu(menu_id)
            sidebar.clear_new_data(menu_id)

    def _focus_table(self, view):
        try:
            from textual.widgets import DataTable
            table = view.query_one(DataTable)
            table.focus()
        except Exception:
            try:
                from textual.containers import VerticalScroll
                scroll = view.query_one(VerticalScroll)
                scroll.focus()
            except Exception:
                view.focus()

    def refresh_sidebar_counts(self):
        monitor = self.service.get_monitor_count()
        paper = len(self.service.get_open_trades())
        archive_count = len(self.service.get_archived_events())
        history = self.service.get_history_count()
        self.query_one("#sidebar", Sidebar).update_counts(monitor, paper, archive_count, history)

    # --- Message handlers ---

    def on_menu_selected(self, message: MenuSelected) -> None:
        self._navigate_to(message.menu_id)

    def on_switch_version_requested(self, message: SwitchVersionRequested) -> None:
        is_analyzing = self._analyzing and self._analyzing_event_id == message.event_id
        self._switch_view(MarketDetailView(
            event_id=message.event_id,
            service=self.service,
            analyzing=is_analyzing,
            version_idx=message.version_idx,
        ))

    def on_view_scan_log_detail(self, message: ViewScanLogDetail) -> None:
        self._switch_view(ScanLogDetailView(message.log_entry, db=self.service.db))

    def on_analyze_requested(self, message: AnalyzeRequested) -> None:
        self._analyzing_event_id = message.event_id
        self._analyzing = True
        # Get event title for status bar
        detail = self.service.get_event_detail(message.event_id)
        title_short = (detail["event"].title[:30] if detail else message.event_id[:30])
        self.query_one("#status-bar", Static).update(f"AI 分析中: {title_short}...")
        self._switch_view(MarketDetailView(
            event_id=message.event_id, service=self.service, analyzing=True,
        ))
        self.run_worker(self._do_analyze, name="analyze", thread=True, exclusive=True)

    def _cancel_analysis(self):
        """Cancel the running AI analysis — triggered by Esc during analysis."""
        if not self._analyzing:
            return
        self._analyzing = False
        self.service.cancel_analysis()
        self.query_one("#status-bar", Static).update("分析已取消")
        if self._analyzing_event_id:
            self._switch_view(MarketDetailView(
                event_id=self._analyzing_event_id, service=self.service,
            ))
            self._analyzing_event_id = None

    async def _do_analyze(self):
        import os
        os.environ["POLILY_TUI"] = "1"
        try:
            event_id = self._analyzing_event_id
            self.service.on_progress = lambda steps: self.app.call_from_thread(
                self._update_progress, steps
            )

            def _heartbeat(elapsed: float, status: str):
                self.app.call_from_thread(self._update_heartbeat, elapsed, status)

            # v0.7.0: ScanService.analyze_event owns the full scan_logs
            # lifecycle (running → completed/failed). We don't write a
            # separate scan_log row here any more.
            await self.service.analyze_event(
                event_id,
                on_heartbeat=_heartbeat,
            )
            self.app.call_from_thread(self._on_analysis_complete, event_id)
        except AnalysisInProgressError as e:
            # Invariant guard hit — another analysis is already running
            # for this event. Surface a friendly notify, not an error modal.
            self.app.call_from_thread(self._on_analysis_failed, str(e))
        except Exception as e:
            error_msg = str(e)
            if "cancelled" in error_msg.lower():
                return  # already handled by _cancel_analysis
            self.app.call_from_thread(self._on_analysis_failed, error_msg)
        finally:
            os.environ.pop("POLILY_TUI", None)
            self._analyzing = False

    def _update_heartbeat(self, elapsed: float, status: str):
        """Update status bar with heartbeat info during AI analysis."""
        title = (self._analyzing_event_id or "")[:25]
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60
        time_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"

        if status == "unresponsive":
            self.query_one("#status-bar", Static).update(
                f"[red]AI 可能遇到问题 ({time_str})[/red] {title} [dim]Esc 取消[/dim]"
            )
        elif status == "long":
            self.query_one("#status-bar", Static).update(
                f"AI 深度分析中，请耐心等待 ({time_str}) {title} [dim]Esc 取消[/dim]"
            )
        elif status == "searching":
            self.query_one("#status-bar", Static).update(
                f"AI 正在搜索分析中 ({time_str}) {title} [dim]Esc 取消[/dim]"
            )
        else:
            self.query_one("#status-bar", Static).update(
                f"AI 分析中 ({time_str}) {title} [dim]Esc 取消[/dim]"
            )

    def _on_analysis_complete(self, event_id: str):
        self.query_one("#status-bar", Static).update("分析完成")
        self.query_one("#sidebar", Sidebar).mark_new_data("tasks")
        self._switch_view(MarketDetailView(event_id=event_id, service=self.service))

    def _on_analysis_failed(self, error: str):
        error_short = error[:80] if len(error) > 80 else error
        self.query_one("#status-bar", Static).update(f"分析失败: {error_short}")
        if self._analyzing_event_id:
            self._switch_view(MarketDetailView(
                event_id=self._analyzing_event_id, service=self.service,
            ))

    def on_cancel_analysis_requested(self, message: CancelAnalysisRequested) -> None:
        self._cancel_analysis()

    def on_cancel_scan_requested(self, message: CancelScanRequested) -> None:
        """Cancel a running scan from the 待办 zone."""
        ok = self.service.cancel_running_scan(message.scan_id)
        if ok:
            self.notify("已取消分析")
        else:
            self.notify("无法取消——该行不在 running 状态", severity="warning")
        # Re-render the scan log view so the row flips to cancelled
        if self._current_menu == "tasks":
            self._navigate_to("tasks")

    def on_open_market_from_log(self, message: OpenMarketFromLog) -> None:
        """Navigate to score result page from a log entry."""
        self._switch_view(
            ScoreResultView(event_id=message.event_id, service=self.service)
        )

    def on_rescore_requested(self, message: RescoreRequested) -> None:
        """Re-score an event by its event_id (looks up slug from DB)."""
        from scanner.core.event_store import get_event
        event = get_event(message.event_id, self.service.db)
        if event and event.slug:
            url = f"https://polymarket.com/event/{event.slug}"
            self.on_add_event_requested(AddEventRequested(url))

    def on_rescore_event_requested(self, message: RescoreEventRequested) -> None:
        """Re-score event from MarketDetailView button."""
        self._rescore_by_event_id(message.event_id)

    def on_score_view_rescore(self, message: ScoreViewRescore) -> None:
        """Re-score event from ScoreResultView button."""
        self._rescore_by_event_id(message.event_id)

    def on_add_to_monitor_requested(self, message: AddToMonitorRequested) -> None:
        """Add event to monitoring from ScoreResultView."""
        self.service.toggle_monitor(message.event_id, enable=True)
        self.refresh_sidebar_counts()
        self._ensure_daemon()
        self._navigate_to("monitor")

    def _ensure_daemon(self) -> None:
        """Auto-start daemon if not running."""
        try:
            from scanner.daemon.scheduler import ensure_daemon_running
            if ensure_daemon_running():
                self.notify("后台监控已自动启动")
        except Exception:
            pass

    def on_back_to_tasks(self, message: BackToTasks) -> None:
        self._navigate_to("tasks")

    def _rescore_by_event_id(self, event_id: str) -> None:
        from scanner.core.event_store import get_event
        event = get_event(event_id, self.service.db)
        if event and event.slug:
            url = f"https://polymarket.com/event/{event.slug}"
            self.on_add_event_requested(AddEventRequested(url))

    def on_view_monitor_detail(self, message: ViewMonitorDetail) -> None:
        """Navigate to event detail from monitor list."""
        self._switch_view(
            MarketDetailView(event_id=message.event_id, service=self.service)
        )

    def on_view_archived_detail(self, message: ViewArchivedDetail) -> None:
        """Row-click in ArchivedEventsView → push MarketDetailView for retrospective view."""
        self._switch_view(
            MarketDetailView(event_id=message.event_id, service=self.service)
        )

    def on_view_trade_detail(self, message: ViewTradeDetail) -> None:
        """Navigate to event detail from portfolio."""
        self._switch_view(
            MarketDetailView(event_id=message.event_id, service=self.service)
        )

    def on_back_to_scan_log(self, message: BackToScanLog) -> None:
        self._navigate_to("tasks")

    def on_back_to_list(self, message: BackToList) -> None:
        self._navigate_to(self._current_menu)

    def _navigate_to(self, menu_id: str):
        if menu_id == "tasks":
            logs = self.service.get_scan_logs()
            current_steps = list(self.service._steps) if self._loading else None
            self._switch_view(ScanLogView(logs, current_steps), "tasks")
        elif menu_id == "monitor":
            self._switch_view(MonitorListView(service=self.service), "monitor")
        elif menu_id == "paper":
            self._switch_view(PaperStatusView(self.service), "paper")
        elif menu_id == "wallet":
            from scanner.tui.views.wallet import WalletView
            self._switch_view(WalletView(self.service), "wallet")
        elif menu_id == "history":
            from scanner.tui.views.history import HistoryView
            self._switch_view(HistoryView(self.service), "history")
        elif menu_id == "archive":
            self._switch_view(ArchivedEventsView(self.service), "archive")
        self._current_menu = menu_id

    def action_show_tasks(self) -> None:
        self._navigate_to("tasks")

    def action_show_monitor(self) -> None:
        self._navigate_to("monitor")

    def action_show_paper(self) -> None:
        self._navigate_to("paper")

    def action_show_wallet(self) -> None:
        self._navigate_to("wallet")

    def action_show_history(self) -> None:
        self._navigate_to("history")

    def action_show_archive(self) -> None:
        self._navigate_to("archive")

    def action_refresh(self) -> None:
        content = self.query_one("#content-area")
        for child in content.children:
            if isinstance(child, MarketDetailView):
                self._switch_view(MarketDetailView(
                    event_id=child.event_id, service=self.service,
                ))
                return
        self._navigate_to(self._current_menu)

    def action_menu_prev(self) -> None:
        idx = self.MENU_ORDER.index(self._current_menu) if self._current_menu in self.MENU_ORDER else 0
        idx = (idx - 1) % len(self.MENU_ORDER)
        self._navigate_to(self.MENU_ORDER[idx])

    def action_menu_next(self) -> None:
        idx = self.MENU_ORDER.index(self._current_menu) if self._current_menu in self.MENU_ORDER else 0
        idx = (idx + 1) % len(self.MENU_ORDER)
        self._navigate_to(self.MENU_ORDER[idx])
