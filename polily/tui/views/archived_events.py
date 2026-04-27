"""ArchivedEventsView: list of events the user was monitoring when they closed.

Data source: `events` + `event_monitors` join (no dedicated archive table).
Rows clickable → navigate to EventDetailView for retrospective view.

v0.8.0 migration:
- PolilyZone atom wraps the list (title: 归档事件)
- Table mounted ONCE in `on_mount`; `_render_all` repopulates via
  `table.clear()` + re-add rows (paper_status lesson: Textual's
  `remove()` is deferred, re-mounting stable-id widgets on the same
  tick trips DuplicateIds)
- Q11 NAV_BINDINGS + view-specific bindings (enter, r)
- Archived events are historical; no bus subscription wired. `r` gives
  the user a manual refresh path if a background resolution adds a new
  row while the view is open.
- Chinese labels throughout; internal event_id not surfaced in visible
  cells (row_keys preserved for ViewArchivedDetail routing)
"""

from __future__ import annotations

import contextlib

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from polily.core.events import TOPIC_LANGUAGE_CHANGED
from polily.tui.bindings import NAV_BINDINGS
from polily.tui.i18n import t
from polily.tui.icons import ICON_COMPLETED
from polily.tui.service import PolilyService
from polily.tui.widgets.polily_zone import PolilyZone


class ViewArchivedDetail(Message):
    """Row-click → navigate to the event's detail page."""

    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


_COLUMN_SPEC = [
    ("title", "archive.col.title"),
    ("score", "archive.col.score"),
    ("count", "archive.col.count"),
    ("closed_at", "archive.col.closed_at"),
]


class ArchivedEventsView(Widget):
    # NOTE: I18nFooter renders binding labels via t(f"binding.{action}") at
    # compose time, so the zh strings below are only fallbacks.
    BINDINGS = [
        Binding("enter", "view_detail", "详情", show=True),
        Binding("r", "refresh", "刷新", show=True),
        *NAV_BINDINGS,
    ]

    DEFAULT_CSS = """
    ArchivedEventsView { height: 1fr; }
    ArchivedEventsView > VerticalScroll { height: 1fr; }
    /* v0.8.0+: stretch zone + table to screen bottom (match paper_status/history). */
    ArchivedEventsView > VerticalScroll > PolilyZone { height: 1fr; }
    ArchivedEventsView DataTable { height: 1fr; }
    ArchivedEventsView .empty-msg { padding: 2; }
    """

    def __init__(self, service: PolilyService):
        super().__init__()
        self.service = service
        self._events: list[dict] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield PolilyZone(
                title=f"{ICON_COMPLETED} {t('archive.title.zone')}",
                id="archive-zone",
            )

    def on_mount(self) -> None:
        """Mount the summary line + table ONCE inside the zone.

        `_render_all` then refreshes them in place via `table.clear()`
        + re-add rows. Re-mounting per render would leak stale widgets
        because Textual's `remove()` is deferred, tripping DuplicateIds
        on stable IDs like `#archive-table`.
        """
        try:
            zone = self.query_one("#archive-zone", PolilyZone)
        except Exception:
            zone = None

        if zone is not None:
            zone.mount(Static("", id="archive-summary"))
            zone.mount(Static(
                "",
                id="archive-empty",
                classes="empty-msg text-center text-muted",
            ))
            table = DataTable(id="archive-table")
            zone.mount(table)
            table.cursor_type = "row"
            for col_key, cat_key in _COLUMN_SPEC:
                table.add_column(t(cat_key), key=col_key)

        self.service.event_bus.subscribe(
            TOPIC_LANGUAGE_CHANGED, self._on_lang_changed,
        )
        self._render_all()

    def on_unmount(self) -> None:
        self.service.event_bus.unsubscribe(
            TOPIC_LANGUAGE_CHANGED, self._on_lang_changed,
        )

    def _on_lang_changed(self, payload: dict) -> None:
        """Update zone title + DataTable column headers on language switch.
        Summary line + count cells are re-rendered by _render_all."""
        with contextlib.suppress(Exception):
            self.query_one("#archive-zone .polily-zone-title", Static).update(
                f"{ICON_COMPLETED} {t('archive.title.zone')}",
            )
            table = self.query_one("#archive-table", DataTable)
            for col_key, cat_key in _COLUMN_SPEC:
                if col_key in table.columns:
                    # See wallet.py for the str → ColumnKey/Text note.
                    table.columns[col_key].label = t(cat_key)  # pyright: ignore[reportArgumentType, reportAttributeAccessIssue]
            table.refresh()
        self._render_all()

    # -- Rendering --

    def _render_all(self) -> None:
        """Refresh summary + DataTable contents in place."""
        try:
            table = self.query_one("#archive-table", DataTable)
        except Exception:
            return

        self._events = self.service.get_archived_events()
        table.clear()

        with contextlib.suppress(Exception):
            self.query_one("#archive-summary", Static).update(
                t("archive.count_summary", count=len(self._events)),
            )

        empty_msg = None
        with contextlib.suppress(Exception):
            empty_msg = self.query_one("#archive-empty", Static)

        if not self._events:
            if empty_msg is not None:
                empty_msg.update(t("archive.empty"))
                empty_msg.display = True
            return

        if empty_msg is not None:
            empty_msg.display = False

        for e in self._events:
            ev = e["event"]
            mc = e["market_count"]
            score_str = f"{ev.structure_score:.0f}" if ev.structure_score else "—"
            # Reuse monitor.* keys — same concept ("X 个" / "二元") and
            # avoiding duplication keeps zh/en in sync naturally.
            count_str = t("monitor.count.format", count=mc) if mc > 1 else t("monitor.count.binary")
            closed_at = (ev.updated_at or "")[:10]  # YYYY-MM-DD
            table.add_row(
                ev.title[:45],
                score_str,
                count_str,
                closed_at,
                key=ev.event_id,
            )

    # -- Selection + navigation --

    def _selected_event_id(self) -> str | None:
        if not self._events:
            return None
        try:
            table = self.query_one("#archive-table", DataTable)
        except Exception:
            return None
        row = table.cursor_row
        if row is None or row < 0 or row >= len(self._events):
            return None
        return self._events[row]["event"].event_id

    def action_view_detail(self) -> None:
        eid = self._selected_event_id()
        if eid:
            self.post_message(ViewArchivedDetail(eid))

    def action_refresh(self) -> None:
        """Manual refresh (Q11 `r` binding) — re-query + rebuild."""
        self._render_all()

    def on_data_table_row_selected(self, _event: DataTable.RowSelected) -> None:
        eid = self._selected_event_id()
        if eid:
            self.post_message(ViewArchivedDetail(eid))
