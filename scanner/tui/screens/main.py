"""MainScreen: Sidebar navigation + Content area with view switching."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from scanner.tui.service import ScanService
from scanner.tui.views.market_detail import (
    AnalyzeRequested,
    BackToList,
    CancelAnalysisRequested,
    MarketDetailView,
    SwitchVersionRequested,
)
from scanner.tui.views.market_list import MarketListView, ViewDetailRequested
from scanner.tui.views.paper_status import AnalyzePositionRequested, PaperStatusView
from scanner.tui.views.position_analysis import BackFromPositionAnalysis, PositionAnalysisView
from scanner.tui.views.scan_log import (
    BackToScanLog,
    OpenMarketFromLog,
    ScanLogDetailView,
    ScanLogView,
    StepInfo,
    ViewScanLogDetail,
)
from scanner.tui.views.notification_list import NotificationListView
from scanner.tui.views.watch_list import ViewWatchDetail, WatchListView
from scanner.tui.widgets.sidebar import MenuSelected, Sidebar


class MainScreen(Screen):
    """Main screen with sidebar navigation and content area."""

    BINDINGS = [
        Binding("0", "show_tasks", "任务"),
        Binding("r", "refresh", "刷新"),
        Binding("s", "new_scan", "扫描"),
        Binding("1", "show_research", "研究"),
        Binding("2", "show_watch", "观察"),
        Binding("3", "show_paper", "持仓"),
        Binding("4", "show_notifications", "通知"),
        Binding("up", "menu_prev", show=False),
        Binding("down", "menu_next", show=False),
    ]

    MENU_ORDER = ["tasks", "research", "watchlist", "paper", "notifications"]

    def __init__(self, service: ScanService):
        super().__init__()
        self.service = service
        self._loading = False
        self._current_menu = "tasks"
        self._analyzing_candidate: object | None = None
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
        states = self.service.get_all_market_states()
        research = len([c for c in self.service.get_research()
                       if not (c.market.market_id in states and states[c.market.market_id].status == "pass")])
        watch = self.service.get_watch_count()
        paper = len(self.service.get_paper_trades())
        notif_count = self.service.get_unread_notification_count()
        sidebar.update_counts(research, watch, paper, notif_count)
        if self.service.tiers:
            self.query_one("#status-bar", Static).update(
                f"上次扫描: 研{research} 观{watch} ({self.service.total_scanned} 市场)"
            )

    def _start_scan(self):
        if self._loading:
            return
        self._loading = True
        self.query_one("#status-bar", Static).update("扫描中...")
        # B5 fix: rebuild ScanLogView with live progress support
        if self._current_menu == "tasks":
            self._navigate_to("tasks")
        self.run_worker(self._do_scan, name="scan", thread=True, exclusive=True)

    async def _do_scan(self):
        """Worker thread: only data fetching, NO direct UI operations."""
        self.service.on_progress = lambda steps: self.app.call_from_thread(
            self._update_progress, steps
        )
        try:
            await self.service.fetch_and_scan()
        except Exception as e:
            self.app.call_from_thread(self._on_scan_failed, str(e))
            return
        self.app.call_from_thread(self._on_scan_complete)

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

    def _on_scan_complete(self):
        """Main thread: update status, do NOT auto-navigate."""
        self._loading = False
        total = self.service.total_scanned
        states = self.service.get_all_market_states()
        research = len([c for c in self.service.get_research()
                       if not (c.market.market_id in states and states[c.market.market_id].status == "pass")])
        watch = self.service.get_watch_count()
        paper = len(self.service.get_paper_trades())

        # Watch summary: count triggered (overdue) and expired
        watch_summary = self.service.get_watch_summary()
        status_parts = [f"扫描完成: 研{research} 观{watch} ({total} 市场)"]
        if watch_summary["total"] > 0:
            parts = []
            if watch_summary["triggered"] > 0:
                parts.append(f"{watch_summary['triggered']}个触发")
            if watch_summary["expired"] > 0:
                parts.append(f"{watch_summary['expired']}个过期")
            if parts:
                status_parts.append(f"观察: {', '.join(parts)}")
        self.query_one("#status-bar", Static).update(" | ".join(status_parts))
        sidebar = self.query_one("#sidebar", Sidebar)
        notif_count = self.service.get_unread_notification_count()
        sidebar.update_counts(research, watch, paper, notif_count)
        # B4 fix: mark pages that have new data, not tasks
        if research:
            sidebar.mark_new_data("research")
        if watch:
            sidebar.mark_new_data("watchlist")

        if self._current_menu == "tasks":
            self._navigate_to("tasks")

    def _on_scan_failed(self, error: str):
        self._loading = False
        error_short = error[:80] if len(error) > 80 else error
        self.query_one("#status-bar", Static).update(f"扫描失败: {error_short}")
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
        states = self.service.get_all_market_states()
        research = len([c for c in self.service.get_research()
                       if not (c.market.market_id in states and states[c.market.market_id].status == "pass")])
        watch = self.service.get_watch_count()
        paper = len(self.service.get_paper_trades())
        notif_count = self.service.get_unread_notification_count()
        self.query_one("#sidebar", Sidebar).update_counts(research, watch, paper, notif_count)

    # --- Message handlers ---

    def on_menu_selected(self, message: MenuSelected) -> None:
        self._navigate_to(message.menu_id)

    def on_view_detail_requested(self, message: ViewDetailRequested) -> None:
        self._switch_view(MarketDetailView(message.candidate, self.service))

    def on_switch_version_requested(self, message: SwitchVersionRequested) -> None:
        is_analyzing = self._analyzing and self._analyzing_candidate is message.candidate
        self._switch_view(MarketDetailView(
            message.candidate, self.service,
            analyzing=is_analyzing,
            version_idx=message.version_idx,
            show_detail=message.show_detail,
        ))

    def on_view_scan_log_detail(self, message: ViewScanLogDetail) -> None:
        self._switch_view(ScanLogDetailView(message.log_entry))

    def on_analyze_requested(self, message: AnalyzeRequested) -> None:
        self._analyzing_candidate = message.candidate
        self._analyzing = True
        title_short = message.candidate.market.title[:30]
        self.query_one("#status-bar", Static).update(f"AI 分析中: {title_short}...")
        self._switch_view(MarketDetailView(message.candidate, self.service, analyzing=True))
        self.run_worker(self._do_analyze, name="analyze", thread=True, exclusive=True)

    def _cancel_analysis(self):
        """Cancel the running AI analysis — triggered by Esc during analysis."""
        if not self._analyzing:
            return
        self._analyzing = False
        self.service.cancel_analysis()
        self.query_one("#status-bar", Static).update("分析已取消")
        if self._analyzing_candidate:
            self._switch_view(MarketDetailView(self._analyzing_candidate, self.service))
            self._analyzing_candidate = None

    async def _do_analyze(self):
        import os
        os.environ["POLILY_TUI"] = "1"
        try:
            candidate = self._analyzing_candidate
            self.service.on_progress = lambda steps: self.app.call_from_thread(
                self._update_progress, steps
            )

            def _heartbeat(elapsed: float, status: str):
                self.app.call_from_thread(self._update_heartbeat, elapsed, status)

            await self.service.analyze_market(
                candidate.market.market_id,
                candidate=candidate,
                on_heartbeat=_heartbeat,
            )
            self.app.call_from_thread(self._on_analysis_complete, candidate)
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
        title = self._analyzing_candidate.market.title[:25] if self._analyzing_candidate else ""
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60
        time_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"

        if status == "unresponsive":
            self.query_one("#status-bar", Static).update(
                f"[red]AI 长时间无响应 ({time_str})[/red] {title} [dim]Esc 取消[/dim]"
            )
        elif status == "slow":
            self.query_one("#status-bar", Static).update(
                f"[yellow]AI 可能在搜索 ({time_str})[/yellow] {title} [dim]Esc 取消[/dim]"
            )
        else:
            self.query_one("#status-bar", Static).update(
                f"AI 分析中 ({time_str}) {title} [dim]Esc 取消[/dim]"
            )

    def _on_analysis_complete(self, candidate):
        self.query_one("#status-bar", Static).update("分析完成")
        self.query_one("#sidebar", Sidebar).mark_new_data("tasks")
        self._switch_view(MarketDetailView(candidate, self.service))

    def _on_analysis_failed(self, error: str):
        error_short = error[:80] if len(error) > 80 else error
        self.query_one("#status-bar", Static).update(f"分析失败: {error_short}")
        if self._analyzing_candidate:
            self._switch_view(MarketDetailView(self._analyzing_candidate, self.service))

    def on_cancel_analysis_requested(self, message: CancelAnalysisRequested) -> None:
        self._cancel_analysis()

    def on_open_market_from_log(self, message: OpenMarketFromLog) -> None:
        """Navigate to market detail from a log entry."""
        candidates = self.service.get_all_candidates()
        for c in candidates:
            if c.market.market_id == message.market_id:
                self._switch_view(MarketDetailView(c, self.service))
                return
        self.notify("未找到该市场（可能需要重新扫描）", severity="warning")

    def on_analyze_position_requested(self, message: AnalyzePositionRequested) -> None:
        """Handle position analysis — dedicated HOLD/REDUCE/EXIT flow."""
        from datetime import UTC, datetime

        trades = self.service.get_paper_trades()
        trade = next((t for t in trades if t.id == message.trade_id), None)
        if not trade:
            self.notify("未找到该持仓", severity="warning")
            return
        candidates = self.service.get_all_candidates()
        candidate = next((c for c in candidates if c.market.market_id == trade.market_id), None)
        if not candidate:
            self.notify("未找到该市场数据（可能需要重新扫描）", severity="warning")
            return

        current_price = candidate.market.yes_price or trade.entry_price
        try:
            marked = datetime.fromisoformat(trade.marked_at)
            days_held = (datetime.now(UTC) - marked).total_seconds() / 86400
        except (ValueError, TypeError):
            days_held = 0
        if trade.side.lower() == "yes" and trade.entry_price > 0:
            pnl_pct = (current_price - trade.entry_price) / trade.entry_price
        elif trade.side.lower() == "no" and (1 - trade.entry_price) > 0:
            pnl_pct = (trade.entry_price - current_price) / (1 - trade.entry_price)
        else:
            pnl_pct = 0

        # Show loading view
        self._switch_view(PositionAnalysisView(
            title=trade.title or candidate.market.title,
            side=trade.side, entry_price=trade.entry_price,
            current_price=current_price, pnl_pct=pnl_pct,
            days_held=days_held, loading=True,
        ))

        # Store context for worker
        self._position_context = {
            "candidate": candidate,
            "entry_price": trade.entry_price,
            "side": trade.side,
            "days_held": days_held,
            "current_price": current_price,
            "pnl_pct": pnl_pct,
            "title": trade.title or candidate.market.title,
        }

        self.query_one("#status-bar", Static).update(f"持仓分析: {trade.title[:30]}...")
        self.run_worker(self._do_position_analyze, name="pos_analyze", thread=True, exclusive=True)

    async def _do_position_analyze(self):
        """Worker: run position analysis."""
        ctx = self._position_context
        try:
            result = await self.service.analyze_position(
                ctx["candidate"], ctx["entry_price"], ctx["side"], ctx["days_held"],
            )
            self.app.call_from_thread(self._on_position_analysis_complete, ctx, result)
        except Exception as e:
            self.app.call_from_thread(self._on_position_analysis_failed, ctx, str(e))

    def _on_position_analysis_complete(self, ctx, result):
        self.query_one("#status-bar", Static).update("持仓分析完成")
        self._switch_view(PositionAnalysisView(
            title=ctx["title"], side=ctx["side"],
            entry_price=ctx["entry_price"], current_price=ctx["current_price"],
            pnl_pct=ctx["pnl_pct"], days_held=ctx["days_held"],
            advice=result,
        ))

    def _on_position_analysis_failed(self, ctx, error):
        self.query_one("#status-bar", Static).update(f"持仓分析失败: {error[:60]}")
        self._switch_view(PositionAnalysisView(
            title=ctx["title"], side=ctx["side"],
            entry_price=ctx["entry_price"], current_price=ctx["current_price"],
            pnl_pct=ctx["pnl_pct"], days_held=ctx["days_held"],
        ))

    def on_back_from_position_analysis(self, message: BackFromPositionAnalysis) -> None:
        self._navigate_to("paper")

    def on_view_watch_detail(self, message: ViewWatchDetail) -> None:
        """Navigate to market detail from watch list."""
        candidates = self.service.get_all_candidates()
        for c in candidates:
            if c.market.market_id == message.market_id:
                self._switch_view(MarketDetailView(c, self.service))
                return
        self.notify("未找到该市场（可能需要重新扫描）", severity="warning")

    def on_back_to_scan_log(self, message: BackToScanLog) -> None:
        self._navigate_to("tasks")

    def on_back_to_list(self, message: BackToList) -> None:
        self._navigate_to(self._current_menu)

    def _navigate_to(self, menu_id: str):
        if menu_id == "tasks":
            logs = self.service.get_scan_logs()
            current_steps = list(self.service._steps) if self._loading else None
            self._switch_view(ScanLogView(logs, current_steps), "tasks")
        elif menu_id == "research":
            states = self.service.get_all_market_states()
            research = [c for c in self.service.get_research()
                       if not (c.market.market_id in states and states[c.market.market_id].status == "pass")]
            self._switch_view(MarketListView(research, self.service, "研究队列"), "research")
        elif menu_id == "watchlist":
            from scanner.market_state import get_watched_markets
            watched = get_watched_markets(self.service.db)
            self._switch_view(WatchListView(watched), "watchlist")
        elif menu_id == "paper":
            self._switch_view(PaperStatusView(self.service), "paper")
        elif menu_id == "notifications":
            self._switch_view(NotificationListView(self.service.db), "notifications")
        self._current_menu = menu_id

    def action_show_tasks(self) -> None:
        self._navigate_to("tasks")

    def action_show_research(self) -> None:
        self._navigate_to("research")

    def action_show_watch(self) -> None:
        self._navigate_to("watchlist")

    def action_show_paper(self) -> None:
        self._navigate_to("paper")

    def action_show_notifications(self) -> None:
        self._navigate_to("notifications")

    def action_refresh(self) -> None:
        self._navigate_to(self._current_menu)

    def action_new_scan(self) -> None:
        self._start_scan()

    def action_menu_prev(self) -> None:
        idx = self.MENU_ORDER.index(self._current_menu) if self._current_menu in self.MENU_ORDER else 0
        idx = (idx - 1) % len(self.MENU_ORDER)
        self._navigate_to(self.MENU_ORDER[idx])

    def action_menu_next(self) -> None:
        idx = self.MENU_ORDER.index(self._current_menu) if self._current_menu in self.MENU_ORDER else 0
        idx = (idx + 1) % len(self.MENU_ORDER)
        self._navigate_to(self.MENU_ORDER[idx])
