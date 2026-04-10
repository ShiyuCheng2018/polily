"""ScanLogView: scan task history + live progress + detail view."""

import contextlib
import time
from dataclasses import dataclass, field
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.scan_log import ScanLogEntry


def _to_local(iso_str: str | None) -> str:
    """Convert ISO 8601 UTC string to local time display."""
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str)
        local_dt = dt.astimezone()
        return local_dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_str[:16].replace("T", " ")


@dataclass
class StepInfo:
    """A single progress step (live, in-memory)."""

    name: str
    status: str = "running"  # running, done, skip, fail
    detail: str = ""
    start_time: float = field(default_factory=time.time)
    elapsed: float = 0.0


class LiveProgress(Static):
    """Shows live step-by-step progress for current scan."""

    SPINNER_FRAMES = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2847\u280f"

    def __init__(self):
        super().__init__("")
        self._steps: list[StepInfo] = []

    def on_mount(self):
        self.set_interval(0.1, self._tick)

    def set_steps(self, steps: list[StepInfo]):
        self._steps = steps
        self._refresh_display()

    def _tick(self):
        for step in self._steps:
            if step.status == "running":
                step.elapsed = time.time() - step.start_time
                self._refresh_display()
                return

    def _spinner_frame(self) -> str:
        idx = int(time.time() * 10) % len(self.SPINNER_FRAMES)
        return self.SPINNER_FRAMES[idx]

    def _refresh_display(self):
        lines = []
        for step in self._steps:
            elapsed_str = f"[dim]{step.elapsed:.1f}s[/dim]"
            if step.status == "running":
                frame = self._spinner_frame()
                line = f"   [bold cyan]{frame}[/bold cyan]  {step.name}     {elapsed_str}"
            elif step.status == "done":
                detail = f"  [cyan]{step.detail}[/cyan]" if step.detail else ""
                line = f"   [green]done[/green]  {step.name}{detail}     {elapsed_str}"
            elif step.status == "skip":
                line = f"   [dim]skip[/dim]  {step.name}     {elapsed_str}"
            elif step.status == "fail":
                line = f"   [red]FAIL[/red]  {step.name}     {elapsed_str}"
            else:
                line = f"         {step.name}     {elapsed_str}"
            lines.append(line)
        self.update("\n\n".join(lines) if lines else "")


# --- Messages ---

class ViewScanLogDetail(Message):
    """Request to view a scan log entry's detail."""
    def __init__(self, log_entry: ScanLogEntry):
        super().__init__()
        self.log_entry = log_entry


class BackToScanLog(Message):
    """Request to go back to scan log list."""
    pass


# --- List View ---

class ScanLogView(Widget):
    """Scan task history with optional live progress at top."""

    DEFAULT_CSS = """
    ScanLogView { height: 1fr; }
    ScanLogView #log-title { padding: 1 0 0 0; text-style: bold; }
    ScanLogView .empty-msg { text-align: center; color: $text-muted; padding: 4; }
    ScanLogView #live-section { padding: 1 0 1 0; }
    ScanLogView #log-table { height: auto; max-height: 60%; }
    """

    def __init__(self, logs: list[ScanLogEntry],
                 current_steps: list[StepInfo] | None = None):
        super().__init__()
        self._logs = logs
        self._current_steps = current_steps
        self._reversed_logs: list[ScanLogEntry] = list(reversed(logs))

    def compose(self) -> ComposeResult:
        yield Static(" 任务记录", id="log-title")

        # Live progress section (only if scanning)
        if self._current_steps is not None:
            with Vertical(id="live-section"):
                yield Static("\n   [dim]--- 当前扫描 ---[/dim]\n")
                yield LiveProgress()

        if not self._logs and self._current_steps is None:
            yield Static(" 还没有扫描记录。按 s 开始扫描。", classes="empty-msg")
        elif self._logs:
            if self._current_steps is not None:
                yield Static("  [dim]--- 历史记录 ---[/dim]")
            yield DataTable(id="log-table")

    def on_mount(self) -> None:
        if self._current_steps is not None:
            with contextlib.suppress(Exception):
                self.query_one(LiveProgress).set_steps(self._current_steps)

        if not self._logs:
            return
        try:
            table = self.query_one("#log-table", DataTable)
        except Exception:
            return
        table.cursor_type = "row"
        table.add_columns("类型", "开始时间", "耗时", "结果", "状态")
        for log in self._reversed_logs:
            started = _to_local(log.started_at)
            elapsed = f"{log.total_elapsed:.1f}s"
            status_text = {"completed": "完成", "failed": "失败", "running": "进行中"}.get(
                log.status, log.status
            )
            if log.type == "analyze":
                type_label = "分析"
                title_short = (log.market_title or "?")[:25]
                result = title_short
            else:
                type_label = "扫描"
                result = f"研{log.research_count} 观{log.watchlist_count} 低分{log.filtered_count}"
            table.add_row(type_label, started, elapsed, result, status_text, key=log.scan_id)

    def update_live_progress(self, steps: list[StepInfo]):
        with contextlib.suppress(Exception):
            self.query_one(LiveProgress).set_steps(steps)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a row — open detail view."""
        try:
            table = self.query_one("#log-table", DataTable)
            row_idx = table.cursor_row
        except Exception:
            return
        if row_idx < len(self._reversed_logs):
            self.post_message(ViewScanLogDetail(self._reversed_logs[row_idx]))


# --- Detail View ---

class OpenMarketFromLog(Message):
    """Request to open event detail from a log entry."""
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class ScanLogDetailView(Widget):
    """Full detail view for a single scan/analyze log entry."""

    BINDINGS = [
        Binding("escape", "go_back", "返回列表"),
        Binding("enter", "open_market", "打开市场", show=False),
    ]

    DEFAULT_CSS = """
    ScanLogDetailView { height: 1fr; }
    ScanLogDetailView .section-title { text-style: bold; color: $primary; padding: 1 0 0 0; }
    ScanLogDetailView .detail-row { padding: 0 0 0 2; }
    ScanLogDetailView .step-row { padding: 0 0 0 2; }
    """

    def __init__(self, log_entry: ScanLogEntry):
        super().__init__()
        self.log_entry = log_entry

    def compose(self) -> ComposeResult:
        log = self.log_entry
        is_analyze = log.type == "analyze"
        status_text = {"completed": "完成", "failed": "失败", "running": "进行中"}.get(
            log.status, log.status
        )

        with VerticalScroll():
            if is_analyze:
                yield Static(f" [bold]分析任务 {log.scan_id}[/bold]", classes="section-title")
                yield Static(f"  市场: {log.market_title or '?'}", classes="detail-row")
                if log.event_id:
                    yield Static("  [dim]按 Enter 打开市场详情[/dim]", classes="detail-row")
            else:
                yield Static(f" [bold]扫描任务 {log.scan_id}[/bold]", classes="section-title")

            # Summary
            yield Static(" 基本信息", classes="section-title")
            yield Static(f"  开始时间: {_to_local(log.started_at)}", classes="detail-row")
            yield Static(f"  结束时间: {_to_local(log.finished_at)}", classes="detail-row")
            yield Static(f"  总耗时:   {log.total_elapsed:.1f}s", classes="detail-row")
            yield Static(f"  状态:     {status_text}", classes="detail-row")

            if log.error:
                yield Static(f"  [red]错误: {log.error}[/red]", classes="detail-row")

            # Results — different for scan vs analyze
            if is_analyze:
                yield Static(" 分析目标", classes="section-title")
                yield Static(f"  市场: {log.market_title or '?'}", classes="detail-row")
                yield Static(f"  ID:   {log.event_id or '?'}", classes="detail-row")
            else:
                yield Static(" 扫描结果", classes="section-title")
                yield Static(f"  市场总数: {log.total_markets}", classes="detail-row")
                yield Static(f"  研究队列: {log.research_count}", classes="detail-row")
                yield Static(f"  观察列表: {log.watchlist_count}", classes="detail-row")
                yield Static(f"  低分:     {log.filtered_count}", classes="detail-row")

            # Steps
            if log.steps:
                yield Static(" 步骤详情", classes="section-title")
                for step in log.steps:
                    elapsed_str = f"[dim]{step.elapsed:.1f}s[/dim]"
                    detail = f"  [cyan]{step.detail}[/cyan]" if step.detail else ""
                    status_label = {
                        "done": "[green]done[/green]",
                        "skip": "[dim]skip[/dim]",
                        "fail": "[red]FAIL[/red]",
                    }.get(step.status, step.status)
                    yield Static(f"  {status_label}  {step.name}{detail}     {elapsed_str}", classes="step-row")

            yield Static("")
            if is_analyze and log.event_id:
                yield Static("  [dim]Enter 打开市场 | Esc 返回列表[/dim]")
            else:
                yield Static("  [dim]Esc 返回列表[/dim]")

    def action_go_back(self) -> None:
        self.post_message(BackToScanLog())

    def action_open_market(self) -> None:
        if self.log_entry.type == "analyze" and self.log_entry.event_id:
            self.post_message(OpenMarketFromLog(self.log_entry.event_id))
