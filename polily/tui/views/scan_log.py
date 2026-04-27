"""ScanLogView: scan task history + live progress + detail view.

v0.8.0 changes:
- ScanLogView(service) — service-driven, not data-driven
- PolilyZone + KVRow atoms for layout
- Bilingual labels via i18n.t() (zh/en) + TOPIC_LANGUAGE_CHANGED bus
  subscription so titles / column headers / button + input placeholders
  flip on F2 without losing scroll/cursor state.
- Event bus subscription (TOPIC_SCAN_UPDATED) for auto-refresh
- Table columns per user-approved mock: 5 for queue, 6 for history
- ScanLogDetailView: no scan_id / event_id exposed to user
- LiveProgress: Nerd Font status indicators (done= / fail= / running=Braille)
"""

import contextlib
import time
from dataclasses import dataclass, field
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Static

from polily.core.events import TOPIC_LANGUAGE_CHANGED, TOPIC_SCAN_UPDATED
from polily.scan_log import ScanLogEntry
from polily.tui._dispatch import dispatch_to_ui
from polily.tui.i18n import t, translate_status
from polily.tui.icons import (
    ICON_COMPLETED,
    ICON_EVENT,
    ICON_FAILED,
    ICON_NOTIFY,
    ICON_USER,
    STATUS_ICONS,
)
from polily.tui.widgets.kv_row import KVRow
from polily.tui.widgets.polily_zone import PolilyZone


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
    """Human-friendly 'when' string for 任务队列 zone. Running rows compute elapsed live.

    The queue mixes `analyze` (分析) and `add_event` (评分) tasks; the live
    label must reflect what the task actually does so the user isn't told
    "正在分析" while a scoring task is running.
    """
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
        key = "scan_log.live.scoring" if log.type == "add_event" else "scan_log.live.analyzing"
        return t(key, elapsed=live)
    if log.scheduled_at:
        try:
            from datetime import UTC, datetime
            sched = datetime.fromisoformat(log.scheduled_at)
            delta = sched - datetime.now(UTC)
            mins = int(delta.total_seconds() // 60)
            when = _to_local(log.scheduled_at)
            if mins < 0:
                return t("scan_log.scheduled.due", when=when)
            if mins < 60:
                return t("scan_log.scheduled.in_minutes", when=when, mins=mins)
            hours = mins // 60
            if hours < 24:
                # Numeric h/m suffix is intentionally locale-neutral.
                return f"{when} ({hours}h {mins%60}m)"
            days = hours // 24
            return f"{when} ({days}d {hours%24}h)"
        except ValueError:
            return _to_local(log.scheduled_at)
    return _to_local(log.started_at)


def _format_elapsed(elapsed: float | None) -> str:
    """Format elapsed seconds as human-friendly string."""
    if elapsed is None or elapsed <= 0:
        return ""
    if elapsed < 60:
        return f"{elapsed:.1f}s"
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)
    return f"{mins}m{secs:02d}s"


def _trigger_icon(source: str) -> str:
    """v0.8.0: map trigger_source enum to Nerd Font glyph."""
    return {
        "scheduled": ICON_EVENT,   # calendar U+F073
        "manual": ICON_USER,       # person U+F007
        "movement": ICON_NOTIFY,   # bell U+F0F3
    }.get(source, "")


def _trigger_who_label(source: str) -> str:
    """Who / what initiated this scan. Icon + i18n label.

    manual / scheduled / movement labels come from the trigger.* catalog
    keys (already shared with translate_trigger). Returns source as-is for
    unknown sources.
    """
    icon_map = {"manual": ICON_USER, "scheduled": ICON_EVENT, "movement": ICON_NOTIFY}
    if source not in icon_map:
        return source
    return f"{icon_map[source]} {t(f'trigger.{source}')}"


def _scan_kind_label(type_: str) -> str:
    """What this scan did. analyze / add_event labels come from
    scan_log.type.* catalog keys."""
    if type_ in ("analyze", "add_event"):
        return t(f"scan_log.type.{type_}")
    return type_


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
                line = f"   [green]{ICON_COMPLETED}[/green]  {step.name}{detail}     {elapsed_str}"
            elif step.status == "skip":
                line = f"   [dim]skip[/dim]  {step.name}     {elapsed_str}"
            elif step.status == "fail":
                line = f"   [red]{ICON_FAILED}[/red]  {step.name}     {elapsed_str}"
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
    """Scan task history with optional live progress at top.

    v0.8.0: service-driven constructor. Fetches logs from service on mount.
    Subscribes to TOPIC_SCAN_UPDATED for auto-refresh.
    """

    # NOTE: I18nFooter renders binding labels via t(f"binding.{action}") at
    # compose time, so the zh strings below are only fallbacks.
    BINDINGS = [
        Binding("c", "cancel_running", "取消正在运行的分析", show=False),
        Binding("r", "refresh", "刷新", show=True),
    ]

    DEFAULT_CSS = """
    ScanLogView { height: 1fr; }
    ScanLogView #url-row { height: auto; padding: 1 1; }
    ScanLogView #url-input { width: 1fr; }
    ScanLogView #score-btn { width: 10; min-width: 10; }
    /* v0.8.0+: pending zone sizes to its rows (natural); history zone
       stretches to fill remaining viewport. */
    ScanLogView #pending-zone { height: auto; max-height: 40%; }
    ScanLogView #history-zone { height: 1fr; }
    ScanLogView #upcoming-table { height: auto; }
    ScanLogView #history-table { height: 1fr; }
    """

    def __init__(self, service):
        super().__init__()
        self.service = service
        # Internal state populated on mount / refresh
        self._logs: list[ScanLogEntry] = []
        self._upcoming: list[ScanLogEntry] = []
        self._history: list[ScanLogEntry] = []

    def compose(self) -> ComposeResult:
        yield Static(t("scan_log.title.records"), id="log-title", classes="bold pt-sm")
        with Horizontal(id="url-row", classes="m-md"):
            yield Input(placeholder=t("scan_log.input.placeholder"), id="url-input")
            yield Button(t("scan_log.button.score"), id="score-btn", variant="primary")

        # Live progress section — shown when service has active steps
        yield Static("", id="live-section-placeholder")

        # Tables are inside PolilyZone atoms
        yield PolilyZone(title=t("scan_log.title.queue"), id="pending-zone")
        yield PolilyZone(title=t("scan_log.title.history"), id="history-zone")

    # Internal column key -> catalog key. Internal keys are stable ids (used
    # nowhere yet but ready for future update_cell calls); visible labels
    # come from t() so they flip on language switch.
    _PENDING_COLS = [
        ("trigger", "scan_log.col.trigger"),
        ("type", "scan_log.col.type"),
        ("status", "scan_log.col.status"),
        ("event", "scan_log.col.event"),
        ("scheduled_at", "scan_log.col.scheduled_at"),
        ("reason", "scan_log.col.reason"),
    ]
    _HISTORY_COLS = [
        ("trigger", "scan_log.col.trigger"),
        ("type", "scan_log.col.type"),
        ("status", "scan_log.col.status"),
        ("event", "scan_log.col.event"),
        ("finished_at", "scan_log.col.finished_at"),
        ("elapsed", "scan_log.col.elapsed"),
        ("error", "scan_log.col.error"),
    ]

    def on_mount(self) -> None:
        # Mount both DataTables ONCE. `_rebuild_*` refreshes rows in
        # place via `table.clear()` so manual `r` refresh doesn't race
        # Textual's deferred `remove()`.
        self._mount_tables()
        self.service.event_bus.subscribe(TOPIC_SCAN_UPDATED, self._on_scan_update)
        self.service.event_bus.subscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)
        self._render_all()

    def _mount_tables(self) -> None:
        try:
            pending_zone = self.query_one("#pending-zone", PolilyZone)
            history_zone = self.query_one("#history-zone", PolilyZone)
        except Exception:
            return
        up_table = DataTable(id="upcoming-table")
        pending_zone.mount(up_table)
        up_table.cursor_type = "row"
        for col_key, cat_key in self._PENDING_COLS:
            up_table.add_column(t(cat_key), key=col_key)

        hist_table = DataTable(id="history-table")
        history_zone.mount(hist_table)
        hist_table.cursor_type = "row"
        for col_key, cat_key in self._HISTORY_COLS:
            hist_table.add_column(t(cat_key), key=col_key)

    def on_unmount(self) -> None:
        self.service.event_bus.unsubscribe(TOPIC_SCAN_UPDATED, self._on_scan_update)
        self.service.event_bus.unsubscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def _on_lang_changed(self, payload: dict) -> None:
        """Update title / static labels / button / input placeholder /
        zone titles / DataTable column headers. Row content is re-rendered
        by _render_all (which re-runs the Chinese-derived helpers like
        _trigger_who_label / _scan_kind_label / translate_status, all of
        which now go through t())."""
        with contextlib.suppress(Exception):
            self.query_one("#log-title", Static).update(t("scan_log.title.records"))
            self.query_one("#url-input", Input).placeholder = t("scan_log.input.placeholder")
            self.query_one("#score-btn", Button).label = t("scan_log.button.score")
            self.query_one("#pending-zone .polily-zone-title", Static).update(t("scan_log.title.queue"))
            self.query_one("#history-zone .polily-zone-title", Static).update(t("scan_log.title.history"))
            up_table = self.query_one("#upcoming-table", DataTable)
            for col_key, cat_key in self._PENDING_COLS:
                if col_key in up_table.columns:
                    # See wallet.py for the str → ColumnKey/Text note.
                    up_table.columns[col_key].label = t(cat_key)  # pyright: ignore[reportArgumentType, reportAttributeAccessIssue]
            up_table.refresh()
            hist_table = self.query_one("#history-table", DataTable)
            for col_key, cat_key in self._HISTORY_COLS:
                if col_key in hist_table.columns:
                    hist_table.columns[col_key].label = t(cat_key)  # pyright: ignore[reportArgumentType, reportAttributeAccessIssue]
            hist_table.refresh()
        self._render_all()

    def _on_scan_update(self, payload: dict) -> None:
        """Bus callback — MUST use call_from_thread (called from non-UI thread)."""
        dispatch_to_ui(self.app, self._render_all)

    def _render_all(self) -> None:
        """Re-fetch logs from service and repopulate both tables."""
        self._logs = self.service.get_scan_logs()
        self._upcoming = _upcoming(self._logs)
        self._history = _history(self._logs)
        self._rebuild_pending_zone()
        self._rebuild_history_zone()

    def _rebuild_pending_zone(self) -> None:
        try:
            table = self.query_one("#upcoming-table", DataTable)
        except Exception:
            return
        table.clear()

        for log in self._upcoming:
            who = _trigger_who_label(log.trigger_source)
            kind = _scan_kind_label(log.type)
            status_icon = STATUS_ICONS.get(log.status, "")
            status_label = f"{status_icon} {translate_status(log.status)}".strip()
            title = (log.market_title or "")[:40]
            when = _format_pending_when(log)
            reason = log.scheduled_reason or ""
            if len(reason) > 15:
                reason = reason[:14] + "…"
            table.add_row(who, kind, status_label, title, when, reason, key=log.scan_id)

    def _rebuild_history_zone(self) -> None:
        try:
            table = self.query_one("#history-table", DataTable)
        except Exception:
            return
        table.clear()

        for log in self._history:
            who = _trigger_who_label(log.trigger_source)
            kind = _scan_kind_label(log.type)
            status_icon = STATUS_ICONS.get(log.status, "")
            status_label = f"{status_icon} {translate_status(log.status)}".strip()
            title = (log.market_title or "")[:40]
            # YY-MM-DD HH:MM — user-friendly short local time with year.
            # Previously `finished[-5:]` grabbed the wrong 5 characters
            # (seconds:00 from the YYYY-MM-DD HH:MM:SS format).
            finished = _to_local(log.finished_at)
            if finished != "?" and len(finished) >= 16:
                fin_short = f"{finished[2:10]} {finished[11:16]}"  # e.g. "26-04-20 10:02"
            else:
                fin_short = "?"
            elapsed_str = _format_elapsed(log.total_elapsed) if log.status == "completed" else ""
            error_str = ""
            if log.error:
                error_str = log.error[:40]
            table.add_row(who, kind, status_label, title, fin_short, elapsed_str, error_str, key=log.scan_id)

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
        # Row-type-aware routing:
        # - add_event (URL-pasted scoring task) → ScoreResultView (评分结果)
        # - analyze / scan / other → ScanLogDetailView (分析详情)
        # Both second-level pages have Enter → EventDetailView (事件详情).
        if log.type == "add_event" and log.event_id:
            self.post_message(OpenEventScoreResult(log.event_id))
        else:
            self.post_message(ViewScanLogDetail(log))

    def action_refresh(self) -> None:
        """Manual refresh — re-fetch logs from service and rebuild zones.

        The bus subscription already auto-updates when scans publish
        TOPIC_SCAN_UPDATED, but `r` gives the user a direct lever when
        they want to force a re-read (e.g., if they suspect a poll tick
        lagged behind a DB write by another process).
        """
        self._render_all()

    def action_cancel_running(self) -> None:
        from polily.tui.views.scan_modals import ConfirmCancelScanModal

        try:
            table = self.query_one("#upcoming-table", DataTable)
        except Exception:
            return
        if table.cursor_row is None or table.cursor_row >= len(self._upcoming):
            return
        log = self._upcoming[table.cursor_row]
        if log.status != "running":
            self.notify(t("scan_log.notify.cancel_running_only"), severity="warning")
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

class OpenEventFromLog(Message):
    """Request to open EventDetailView from a log context.

    Emitted from:
    - ScanLogDetailView Enter binding (分析详情 → 事件详情)
    - ScoreResultView Enter binding (评分结果 → 事件详情)
    """
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class OpenEventScoreResult(Message):
    """Request to open ScoreResultView (评分结果) from a log entry.

    Emitted from the scan_log list when user presses Enter on an
    `add_event` row. This is a shortcut — add_event rows are scoring
    tasks whose natural destination is the 5-dim score breakdown page.
    """
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class RescoreRequested(Message):
    """Request to re-score an event from log detail."""
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class ScanLogDetailView(Widget):
    """Full detail view for a single scan/analyze log entry.

    v0.8.0: PolilyZone + KVRow atoms. scan_id and event_id are NOT shown
    to users (internal identifiers only).
    """

    # NOTE: I18nFooter renders binding labels via t(f"binding.{action}") at
    # compose time. action="go_back" maps to binding.go_back ("返回" / "Back");
    # if you want the longer "返回列表" wording, add a dedicated key under
    # scan_log.binding.go_back_list and route there.
    BINDINGS = [
        Binding("escape", "go_back", "返回列表"),
        Binding("enter", "open_event", "打开事件", show=True),
        Binding("o", "open_link", "链接", show=True),
        Binding("r", "refresh", "刷新", show=True),
    ]

    DEFAULT_CSS = """
    ScanLogDetailView { height: 1fr; }
    ScanLogDetailView .step-row { padding: 0 0 0 2; }
    """

    def __init__(self, log_entry: ScanLogEntry, db=None):
        super().__init__()
        self.log_entry = log_entry
        self._db = db

    def on_mount(self) -> None:
        from polily.core.events import get_event_bus
        get_event_bus().subscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def on_unmount(self) -> None:
        from polily.core.events import get_event_bus
        get_event_bus().unsubscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def _on_lang_changed(self, payload: dict) -> None:
        """Static snapshot view — recompose to re-evaluate every t() call."""
        dispatch_to_ui(self.app, lambda: self.refresh(recompose=True))

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
                    date = iso_str[:10]
                    if days < 0:
                        return t("scan_log.time.days_ago", date=date, days=abs(days))
                    elif days == 0:
                        return t("scan_log.time.hours_later", date=date, hours=hours)
                    elif days == 1:
                        return t("scan_log.time.tomorrow", date=date)
                    else:
                        return t("scan_log.time.days_later", date=date, days=days)
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

    def _find_analysis_version(self):
        """Find the AnalysisVersion produced by this scan_log entry.

        Only relevant for `analyze` + `completed`. Matches by event_id +
        created_at falling within the scan_log's time window. If multiple
        matches, returns the latest (highest version).
        """
        log = self.log_entry
        if log.type != "analyze" or log.status != "completed":
            return None
        if not self._db or not log.event_id:
            return None
        try:
            from polily.analysis_store import get_event_analyses
            versions = get_event_analyses(log.event_id, self._db)
            if not versions:
                return None
            started = log.started_at or ""
            finished = log.finished_at or "9999"
            matching = [
                v for v in versions
                if started <= (v.created_at or "") <= finished
            ]
            if matching:
                return matching[-1]
            # Fallback: the latest analysis for this event (within the
            # same day as scan's finished_at, to avoid mismatching old runs)
            return versions[-1]
        except Exception:
            return None

    def compose(self) -> ComposeResult:
        log = self.log_entry
        is_analyze = log.type == "analyze"
        is_add_event = log.type == "add_event"

        status_icon = STATUS_ICONS.get(log.status, "")
        status_label = f"{status_icon} {translate_status(log.status)}".strip()
        trigger_label = _trigger_who_label(log.trigger_source)
        kind_label = _scan_kind_label(log.type)

        zone_title = t("scan_log.title.detail.analysis") if is_analyze else t("scan_log.title.detail.scan")

        # For completed analyze runs, try to locate the produced version.
        analysis_version = self._find_analysis_version()

        with VerticalScroll():
            with PolilyZone(title=zone_title):
                # event title — no event_id prefix
                yield KVRow(label=t("scan_log.kv.event"), value=log.market_title or "?")
                yield KVRow(label=t("scan_log.kv.status"), value=status_label)
                yield KVRow(label=t("scan_log.kv.trigger"), value=trigger_label)
                yield KVRow(label=t("scan_log.kv.kind"), value=kind_label)
                if analysis_version is not None:
                    yield KVRow(label=t("scan_log.kv.version"), value=f"v{analysis_version.version}")
                yield KVRow(label=t("scan_log.kv.started_at"), value=_to_local(log.started_at))
                yield KVRow(label=t("scan_log.kv.finished_at"), value=_to_local(log.finished_at))
                elapsed_display = _format_elapsed(log.total_elapsed) or "?"
                yield KVRow(label=t("scan_log.kv.elapsed"), value=elapsed_display)
                if log.scheduled_reason:
                    yield KVRow(label=t("scan_log.kv.reason"), value=log.scheduled_reason)
                if log.status == "failed" and log.error:
                    yield KVRow(label=t("scan_log.kv.error"), value=log.error)

                # Results summary for add_event / scan type
                if is_add_event or (not is_analyze):
                    stats = self._get_scan_stats()
                    if stats and (is_add_event or not is_analyze):
                        yield KVRow(
                            label=t("scan_log.kv.events_markets_count"),
                            value=t(
                                "scan_log.kv.events_markets_value",
                                events=stats["research_events"],
                                markets=stats["research_markets"],
                            ),
                        )

            # Analysis content — reuse the EventDetailView AnalysisPanel
            # (markdown render + full narrative structure). AnalysisPanel
            # supplies its own DashPanel border + "AI 分析" title, so no
            # outer PolilyZone (avoid nested borders — see commit 93b23e1).
            # Version number is already shown as KVRow in the meta zone above.
            if analysis_version is not None:
                from polily.tui.components import AnalysisPanel
                yield AnalysisPanel(
                    analyses=[analysis_version], version_idx=0, analyzing=False,
                )

            # Steps zone
            if log.steps:
                with PolilyZone(title=t("scan_log.title.detail.steps")):
                    for step in log.steps:
                        elapsed_str = f"[dim]{step.elapsed:.1f}s[/dim]"
                        detail = f"  [cyan]{step.detail}[/cyan]" if step.detail else ""
                        status_label_step = {
                            "done": f"[green]{ICON_COMPLETED}[/green]",
                            "skip": "[dim]skip[/dim]",
                            "fail": f"[red]{ICON_FAILED}[/red]",
                        }.get(step.status, step.status)
                        yield Static(
                            f"  {status_label_step}  {step.name}{detail}     {elapsed_str}",
                            classes="step-row",
                        )

            yield Static("")
            # Action buttons — keyboard hints live in the footer (via BINDINGS show=True).
            if is_add_event and log.event_id:
                yield Button(t("scan_log.button.rescore"), id="rescore-btn", variant="primary")

    def action_refresh(self) -> None:
        """Manual refresh — reload the log entry from DB and recompose.

        A scan_log row is mostly immutable once finalized, but a
        `running` row the user is watching grows (steps, elapsed), and
        an `analyze` row's produced AnalysisVersion is written at
        completion — `r` lets the user pull the latest snapshot.
        """
        from polily.scan_log import load_scan_logs

        if not self._db:
            return
        fresh = next(
            (e for e in load_scan_logs(self._db, limit=200)
             if e.scan_id == self.log_entry.scan_id),
            None,
        )
        if fresh is not None:
            self.log_entry = fresh
        self.refresh(recompose=True)

    def action_go_back(self) -> None:
        self.post_message(BackToScanLog())

    def action_open_event(self) -> None:
        if self.log_entry.event_id:
            self.post_message(OpenEventFromLog(self.log_entry.event_id))

    def action_open_link(self) -> None:
        """`o` → open the Polymarket event page in the system browser.

        Resolves slug via `get_event(event_id, db)`; scan_log rows without
        an event_id (shouldn't happen for analyze / add_event, but the
        field is nullable) or with a null slug get a toast instead.
        """
        from polily.core.event_store import get_event

        if not self.log_entry.event_id or not self._db:
            self.notify(t("scan_log.notify.no_link"), severity="warning")
            return
        event = get_event(self.log_entry.event_id, self._db)
        slug = getattr(event, "slug", None) if event else None
        if not slug:
            self.notify(t("scan_log.notify.no_link"), severity="warning")
            return
        import webbrowser
        url = f"https://polymarket.com/event/{slug}"
        try:
            webbrowser.open(url)
        except Exception:
            self.notify(t("scan_log.notify.cannot_open_browser"), severity="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rescore-btn" and self.log_entry.event_id:
            self.post_message(RescoreRequested(self.log_entry.event_id))
