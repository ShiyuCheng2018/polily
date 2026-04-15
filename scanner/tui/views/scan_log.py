"""ScanLogView: scan task history + live progress + detail view."""

import contextlib
import time
from dataclasses import dataclass, field
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Static

from scanner.scan_log import ScanLogEntry


def _to_local(iso_str: str | None) -> str:
    """Convert ISO 8601 UTC string to local time display."""
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str)
        local_dt = dt.astimezone()
        return local_dt.strftime("%Y-%m-%d %H:%M:%S")
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


class AddEventRequested(Message):
    """User submitted a Polymarket URL to add."""
    def __init__(self, url: str):
        super().__init__()
        self.url = url


# --- List View ---

class ScanLogView(Widget):
    """Scan task history with optional live progress at top."""

    DEFAULT_CSS = """
    ScanLogView { height: 1fr; }
    ScanLogView #log-title { padding: 1 0 0 0; text-style: bold; }
    ScanLogView #url-row { height: auto; padding: 1 1; margin: 1 0; }
    ScanLogView #url-input { width: 1fr; }
    ScanLogView #score-btn { width: 10; min-width: 10; }
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
        with Horizontal(id="url-row"):
            yield Input(placeholder="粘贴 Polymarket 链接...", id="url-input")
            yield Button("评分", id="score-btn", variant="primary")

        # Live progress section
        if self._current_steps is not None:
            with Vertical(id="live-section"):
                yield Static("\n   [dim]--- 进行中 ---[/dim]\n")
                yield LiveProgress()

        if not self._logs and self._current_steps is None:
            yield Static(" 粘贴 Polymarket 事件链接开始评分。", classes="empty-msg")
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
                type_label = "AI 分析"
                title_short = (log.market_title or "?")[:25]
                result = title_short
            elif log.type == "add_event":
                type_label = "评分"
                title_short = (log.market_title or "?")[:25]
                result = title_short
            else:
                type_label = "扫描"
                total = log.research_count + log.watchlist_count
                result = f"{total} 事件"
            table.add_row(type_label, started, elapsed, result, status_text, key=log.scan_id)

    def _submit_url(self) -> None:
        try:
            inp = self.query_one("#url-input", Input)
        except Exception:
            return
        url = inp.value.strip()
        if url:
            self.post_message(AddEventRequested(url))
            inp.value = ""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit_url()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "score-btn":
            self._submit_url()

    def update_live_progress(self, steps: list[StepInfo]):
        with contextlib.suppress(Exception):
            self.query_one(LiveProgress).set_steps(steps)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a row — open detail view. add_event goes directly to event detail."""
        try:
            table = self.query_one("#log-table", DataTable)
            row_idx = table.cursor_row
        except Exception:
            return
        if row_idx < len(self._reversed_logs):
            log = self._reversed_logs[row_idx]
            if log.type == "add_event" and log.event_id:
                self.post_message(OpenMarketFromLog(log.event_id))
            else:
                self.post_message(ViewScanLogDetail(log))


# --- Detail View ---

class OpenMarketFromLog(Message):
    """Request to open event detail from a log entry."""
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class RescoreRequested(Message):
    """Request to re-score an event from log detail."""
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

    def __init__(self, log_entry: ScanLogEntry, db=None):
        super().__init__()
        self.log_entry = log_entry
        self._db = db

    def _get_scan_stats(self) -> dict | None:
        """Query rich scan statistics from DB."""
        if not self._db:
            return None
        try:
            conn = self._db.conn
            # Research events + markets
            r = conn.execute(
                "SELECT COUNT(*) FROM events WHERE structure_score IS NOT NULL AND closed=0"
            ).fetchone()
            research_events = r[0] if r else 0
            r = conn.execute(
                "SELECT COUNT(*) FROM markets m JOIN events e ON m.event_id=e.event_id "
                "WHERE e.structure_score IS NOT NULL AND e.closed=0"
            ).fetchone()
            research_markets = r[0] if r else 0

            # Type distribution
            rows = conn.execute(
                "SELECT COALESCE(market_type,'other'), COUNT(*) FROM events "
                "WHERE structure_score IS NOT NULL AND closed=0 "
                "GROUP BY market_type ORDER BY COUNT(*) DESC"
            ).fetchall()
            type_summary = " | ".join(f"{row[0]}: {row[1]}" for row in rows) if rows else "-"

            # Score range
            r = conn.execute(
                "SELECT MIN(structure_score), MAX(structure_score) FROM events "
                "WHERE structure_score IS NOT NULL AND closed=0"
            ).fetchone()
            score_min = r[0] or 0
            score_max = r[1] or 0

            # End date range with relative time
            from datetime import UTC, datetime
            r = conn.execute(
                "SELECT MIN(end_date), MAX(end_date) FROM events "
                "WHERE end_date IS NOT NULL AND closed=0 AND structure_score IS NOT NULL"
            ).fetchone()
            now = datetime.now(UTC)

            def _fmt_end(iso_str):
                if not iso_str:
                    return "-"
                try:
                    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
                    delta = dt - now
                    days = delta.days
                    hours = delta.seconds // 3600
                    if days < 0:
                        return f"{iso_str[:10]} ({abs(days)}天前)"
                    elif days == 0:
                        return f"{iso_str[:10]} ({hours}小时后)"
                    elif days == 1:
                        return f"{iso_str[:10]} (明天)"
                    else:
                        return f"{iso_str[:10]} ({days}天后)"
                except (ValueError, TypeError):
                    return iso_str[:10] if iso_str else "-"

            earliest = _fmt_end(r[0]) if r else "-"
            latest = _fmt_end(r[1]) if r else "-"

            return {
                "research_events": research_events,
                "research_markets": research_markets,
                "type_summary": type_summary,
                "score_min": score_min,
                "score_max": score_max,
                "earliest_end": earliest,
                "latest_end": latest,
            }
        except Exception:
            return None

    def compose(self) -> ComposeResult:
        log = self.log_entry
        is_analyze = log.type == "analyze"
        is_add_event = log.type == "add_event"
        status_text = {"completed": "完成", "failed": "失败", "running": "进行中"}.get(
            log.status, log.status
        )

        with VerticalScroll():
            if is_analyze:
                yield Static(f" [bold]AI 分析 {log.scan_id}[/bold]", classes="section-title")
                yield Static(f"  事件: {log.market_title or '?'}", classes="detail-row")
                if log.event_id:
                    yield Static("  [dim]按 Enter 打开事件详情[/dim]", classes="detail-row")
            elif is_add_event:
                yield Static(f" [bold]评分任务 {log.scan_id}[/bold]", classes="section-title")
                yield Static(f"  事件: {log.market_title or '?'}", classes="detail-row")
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

            # Results — different by type
            if is_analyze:
                yield Static(" 分析目标", classes="section-title")
                yield Static(f"  事件: {log.market_title or '?'}", classes="detail-row")
                yield Static(f"  ID:   {log.event_id or '?'}", classes="detail-row")
            elif is_add_event:
                yield Static(" 评分结果", classes="section-title")
                stats = self._get_scan_stats()
                if stats:
                    yield Static(f"  事件数: {stats['research_events']} 事件 / {stats['research_markets']} 市场", classes="detail-row")
                    yield Static(f"  类型分布: {stats['type_summary']}", classes="detail-row")
                    yield Static(f"  评分区间: {stats['score_min']:.0f} ~ {stats['score_max']:.0f}", classes="detail-row")
                    yield Static(f"  最近过期: {stats['earliest_end']}", classes="detail-row")
                    yield Static(f"  最晚过期: {stats['latest_end']}", classes="detail-row")
            else:
                yield Static(" 扫描结果", classes="section-title")
                stats = self._get_scan_stats()
                if stats:
                    yield Static(f"  事件数: {stats['research_events']} 事件 / {stats['research_markets']} 市场", classes="detail-row")
                    yield Static(f"  类型分布: {stats['type_summary']}", classes="detail-row")
                else:
                    yield Static(f"  事件总数: {log.research_count + log.watchlist_count}", classes="detail-row")

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
            # Action buttons
            if is_add_event and log.event_id:
                yield Button("重新评分", id="rescore-btn", variant="primary")
                yield Static("")
                yield Static("  [dim]Esc 返回列表[/dim]")
            elif is_analyze and log.event_id:
                yield Static("  [dim]Enter 打开事件 | Esc 返回列表[/dim]")
            else:
                yield Static("  [dim]Esc 返回列表[/dim]")

    def action_go_back(self) -> None:
        self.post_message(BackToScanLog())

    def action_open_market(self) -> None:
        if self.log_entry.event_id:
            self.post_message(OpenMarketFromLog(self.log_entry.event_id))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rescore-btn" and self.log_entry.event_id:
            self.post_message(RescoreRequested(self.log_entry.event_id))
