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


_UPCOMING_STATUSES = {"pending", "running"}


def _upcoming(logs: list[ScanLogEntry]) -> list[ScanLogEntry]:
    """Rows shown in the 待办 zone. Running on top; pending by scheduled_at asc."""
    upc = [e for e in logs if e.status in _UPCOMING_STATUSES]

    def sort_key(e: ScanLogEntry) -> tuple[int, str]:
        # running sorts before pending
        bucket = 0 if e.status == "running" else 1
        ts = e.scheduled_at or e.started_at or ""
        return (bucket, ts)

    return sorted(upc, key=sort_key)


def _history(logs: list[ScanLogEntry]) -> list[ScanLogEntry]:
    """Rows shown in the 历史 zone. Newest first."""
    hist = [e for e in logs if e.status not in _UPCOMING_STATUSES]
    return sorted(hist, key=lambda e: e.started_at or "", reverse=True)


def _format_pending_when(log: ScanLogEntry) -> str:
    """Human-friendly 'when' string for 待办 zone. Running rows compute elapsed live."""
    if log.status == "running":
        # total_elapsed persists only at finish_scan; compute live for UI
        try:
            from datetime import UTC, datetime
            started = datetime.fromisoformat(log.started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            live = (datetime.now(UTC) - started).total_seconds()
        except (ValueError, TypeError):
            live = 0.0
        return f"正在分析... ({live:.0f}s)"
    if log.scheduled_at:
        try:
            from datetime import UTC, datetime
            sched = datetime.fromisoformat(log.scheduled_at)
            delta = sched - datetime.now(UTC)
            mins = int(delta.total_seconds() // 60)
            if mins < 0:
                return f"{_to_local(log.scheduled_at)} (已到)"
            if mins < 60:
                return f"{_to_local(log.scheduled_at)} ({mins}分)"
            hours = mins // 60
            if hours < 24:
                return f"{_to_local(log.scheduled_at)} ({hours}h {mins%60}m)"
            days = hours // 24
            return f"{_to_local(log.scheduled_at)} ({days}d {hours%24}h)"
        except ValueError:
            return _to_local(log.scheduled_at)
    return _to_local(log.started_at)


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


class CancelScanRequested(Message):
    """Request to cancel a running scan."""
    def __init__(self, scan_id: str):
        super().__init__()
        self.scan_id = scan_id


# --- List View ---

class ScanLogView(Widget):
    """Scan task history with optional live progress at top."""

    BINDINGS = [
        Binding("c", "cancel_running", "取消正在运行的分析", show=False),
    ]

    DEFAULT_CSS = """
    ScanLogView { height: 1fr; }
    ScanLogView #log-title { padding: 1 0 0 0; text-style: bold; }
    ScanLogView #url-row { height: auto; padding: 1 1; margin: 1 0; }
    ScanLogView #url-input { width: 1fr; }
    ScanLogView #score-btn { width: 10; min-width: 10; }
    ScanLogView .empty-msg { text-align: center; color: $text-muted; padding: 4; }
    ScanLogView #live-section { padding: 1 0 1 0; }
    ScanLogView .zone-title { padding: 1 0 0 0; text-style: bold; color: $primary; }
    ScanLogView DataTable { height: auto; max-height: 40%; }
    """

    def __init__(
        self,
        logs: list[ScanLogEntry],
        current_steps: list[StepInfo] | None = None,
    ):
        super().__init__()
        self._logs = logs
        self._current_steps = current_steps
        self._upcoming = _upcoming(logs)
        self._history = _history(logs)
        self._reversed_logs = list(reversed(logs))  # keep for any external caller

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

        # Empty state
        if self._current_steps is None and not (self._upcoming or self._history):
            yield Static(" 粘贴 Polymarket 事件链接开始评分。", classes="empty-msg")
            return

        # Optional separator between live + history when both exist
        if self._current_steps is not None and (self._upcoming or self._history):
            yield Static("  [dim]--- 历史记录 ---[/dim]")

        if self._upcoming:
            yield Static(f"─ 待办 ({len(self._upcoming)}) ─", classes="zone-title")
            yield DataTable(id="upcoming-table")
        if self._history:
            yield Static(f"─ 历史 ({len(self._history)}) ─", classes="zone-title")
            yield DataTable(id="history-table")

    def on_mount(self) -> None:
        if self._current_steps is not None:
            with contextlib.suppress(Exception):
                self.query_one(LiveProgress).set_steps(self._current_steps)
        self._populate_upcoming()
        self._populate_history()

    def _populate_upcoming(self):
        try:
            table = self.query_one("#upcoming-table", DataTable)
        except Exception:
            return
        table.cursor_type = "row"
        table.add_columns("状态", "事件", "预计", "来源")
        for log in self._upcoming:
            icon = "🔵" if log.status == "running" else "🟡"
            when = _format_pending_when(log)
            source = log.trigger_source
            title = (log.market_title or "?")[:25]
            table.add_row(f"{icon} {log.status}", title, when, source, key=log.scan_id)

    def _populate_history(self):
        try:
            table = self.query_one("#history-table", DataTable)
        except Exception:
            return
        table.cursor_type = "row"
        table.add_columns("状态", "事件", "时间", "耗时", "来源")
        for log in self._history:
            icon = {"completed": "✅", "failed": "❌",
                    "cancelled": "⚪", "superseded": "⚪"}.get(log.status, "·")
            started = _to_local(log.started_at)
            elapsed = f"{log.total_elapsed:.1f}s" if log.status == "completed" else ""
            source = log.trigger_source
            title = (log.market_title or "?")[:25]
            table.add_row(f"{icon} {log.status}", title, started, elapsed, source, key=log.scan_id)

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
            table = event.data_table
        except Exception:
            return
        if table.id == "upcoming-table":
            rows = self._upcoming
        elif table.id == "history-table":
            rows = self._history
        else:
            return
        row_idx = table.cursor_row
        if row_idx is None or row_idx >= len(rows):
            return
        log = rows[row_idx]
        if log.type == "add_event" and log.event_id:
            self.post_message(OpenMarketFromLog(log.event_id))
        else:
            self.post_message(ViewScanLogDetail(log))

    def action_cancel_running(self) -> None:
        from scanner.tui.views.scan_modals import ConfirmCancelScanModal

        try:
            table = self.query_one("#upcoming-table", DataTable)
        except Exception:
            return
        if table.cursor_row is None or table.cursor_row >= len(self._upcoming):
            return
        log = self._upcoming[table.cursor_row]
        if log.status != "running":
            self.notify("只能取消正在运行的分析", severity="warning")
            return
        # Compute live elapsed for the modal display
        live_elapsed = 0.0
        try:
            from datetime import UTC, datetime
            started = datetime.fromisoformat(log.started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            live_elapsed = (datetime.now(UTC) - started).total_seconds()
        except (ValueError, TypeError):
            pass

        modal = ConfirmCancelScanModal(
            event_title=log.market_title or "?",
            elapsed_seconds=live_elapsed,
        )
        scan_id = log.scan_id

        def on_close(confirmed: bool | None):
            if confirmed:
                self.post_message(CancelScanRequested(scan_id))

        self.app.push_screen(modal, on_close)


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
