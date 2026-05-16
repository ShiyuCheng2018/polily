"""AnalysisPanel: v0.12.0 dispatching analysis renderer.

Public API preserved from v0.11.x:
    AnalysisPanel(analyses, version_idx=-1, analyzing=False)
    .update_data(analyses, version_idx=-1, analyzing=False)

Internally, the body for the *current version* is rendered via:
  - narrative_format='markdown' → MarkdownAnalysisView (WYSIWYG)
  - narrative_format='json'     → _compose_legacy_body (legacy renderer)

The version selector + DashPanel framing + analyzing indicator behave
exactly as in v0.11.x — every existing call site (event_detail.py:209,
scan_log.py:891) continues to work without modification.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from polily.tui.components.legacy_analysis_panel import _compose_legacy_body
from polily.tui.components.markdown_analysis_view import MarkdownAnalysisView
from polily.tui.i18n import t
from polily.tui.widgets.cards import DashPanel


class AnalysisPanel(Widget):
    """AI analysis panel — dispatches body per version's narrative_format.

    Constructor & update_data signatures match v0.11.x byte-for-byte so
    every existing caller keeps working.
    """

    DEFAULT_CSS = """
    AnalysisPanel { height: auto; }
    AnalysisPanel DashPanel { width: 1fr; margin: 0 1; height: auto; }
    AnalysisPanel .section-label { text-style: bold; color: $primary; padding: 1 0 0 1; }
    AnalysisPanel .row { padding: 0 0 0 1; }
    """

    def __init__(self, analyses: list, version_idx: int = -1, analyzing: bool = False):
        super().__init__()
        self._analyses = analyses
        self._version_idx = version_idx
        self._analyzing = analyzing

        if analyses and version_idx < 0:
            self._version_idx = len(analyses) - 1

    def compose(self) -> ComposeResult:
        if self._analyzing:
            yield Static(f"[dim]{t('analysis.analyzing')}[/dim]", classes="row")

        if not self._analyses:
            if not self._analyzing:
                yield Static("")
            return

        if self._version_idx < 0:
            return

        av = self._analyses[self._version_idx]
        if not av.narrative_output:
            return

        panel = DashPanel(id="panel-analysis")
        panel.border_title = t("analysis.title")
        with panel:
            # Body — dispatch per narrative_format
            if av.narrative_format == "markdown":
                yield MarkdownAnalysisView(av)
            else:  # 'json' or any legacy / unrecognized value
                yield from _compose_legacy_body(av)

            yield Static("")
            yield from self._render_version_selector()

    def _render_version_selector(self) -> ComposeResult:
        if not self._analyses or self._version_idx < 0:
            return
        v = self._analyses[self._version_idx]
        total = len(self._analyses)
        idx = self._version_idx + 1
        from datetime import datetime
        try:
            utc_dt = datetime.fromisoformat(v.created_at)
            local_dt = utc_dt.astimezone()
            ts = local_dt.strftime("%m-%d %H:%M")
        except (ValueError, TypeError):
            ts = v.created_at[5:16].replace("T", " ")

        # trigger label maps to existing trigger.* catalog keys (manual /
        # scheduled / movement). Unknown triggers render the raw value.
        trigger_label = (
            t(f"trigger.{v.trigger_source}")
            if v.trigger_source in ("manual", "scheduled", "movement")
            else v.trigger_source
        )
        yield Static(
            f"[dim]{t('analysis.version_footer', version=v.version, ts=ts, trigger=trigger_label, idx=idx, total=total)}[/dim]",
            classes="row",
        )

    def update_data(
        self,
        analyses: list,
        version_idx: int = -1,
        analyzing: bool = False,
    ) -> None:
        """v0.10.1 in-place refresh — recompose self.

        Markdown widgets without stable IDs make per-widget update
        impractical. Recomposing AnalysisPanel itself is safe: the outer
        VerticalScroll lives on EventDetailView, and Textual's recompose
        is scoped to widget+descendants. The user's scroll position lives
        in the outer VerticalScroll and is preserved.
        """
        self._analyses = analyses
        self._version_idx = version_idx
        self._analyzing = analyzing
        if analyses and version_idx < 0:
            self._version_idx = len(analyses) - 1
        self.refresh(recompose=True)
