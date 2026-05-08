"""LegacyAnalysisPanel: AI analysis display for v0.11.x JSON narrative_output rows.

Kept after v0.12.0 for backward-compat rendering of analyses with
narrative_format='json'. The new dispatcher in `analysis_panel.py`
delegates to `_compose_legacy_body` for json-format rows.
"""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Markdown, Static

from polily.analysis_store import AnalysisVersion
from polily.tui.i18n import t
from polily.tui.widgets.cards import DashPanel

CONFIDENCE_BAR = {
    "low": "[red]██[/red][dim]██████[/dim]",
    "medium": "[yellow]█████[/yellow][dim]███[/dim]",
    "high": "[green]███████[/green][dim]█[/dim]",
}


def _format_stop_loss_or_take_profit(label: str, v: object) -> str:
    """Render stop_loss / take_profit value in the new {side, price}
    schema; gracefully render legacy bare-float fixtures from pre-v0.11.7
    analyses rows.

    New format:    "<label> YES @ $0.55"  (label from t('analysis.stop_loss'))
    Legacy format: "<label> $0.55"  (no side info available; render as-is)
    """
    if isinstance(v, dict) and "side" in v and "price" in v:
        return f"{label} {v['side'].upper()} @ ${v['price']:.2f}"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        # Legacy bare float — pre-v0.11.7 analyses fixture in DB.
        return f"{label} ${v:.2f}"
    # Defensive fallback (shouldn't reach here under v0.11.7+ schema).
    return f"{label} {v!r}"


def _compose_legacy_body(av: AnalysisVersion) -> ComposeResult:
    """Render the body widgets for a single legacy ('json' narrative_format)
    analysis version. Yields the operations / position / analysis / research /
    risk / summary / next-check widget tree.

    Used by both `LegacyAnalysisPanel` (kept for back-compat) and the new
    dispatching `AnalysisPanel` in `analysis_panel.py` for json-format rows.
    """
    n = av.narrative_output if av.narrative_output else None
    if not isinstance(n, dict) or not n:
        return

    # Operations
    ops = n.get("operations", [])
    yield Static(f"── {t('analysis.section.operations')} ──", classes="section-label")
    for op in ops:
        action = op.get("action", "")
        title = op.get("market_title", "")
        entry = op.get("entry_price")
        size = op.get("position_size_usd")
        reasoning = op.get("reasoning", "")

        conf = op.get("confidence", "")
        conf_bar = CONFIDENCE_BAR.get(conf, "")
        conf_label = t(f"analysis.confidence.{conf}") if conf in ("low", "medium", "high") else ""
        conf_str = f"  {conf_bar} {conf_label}" if conf_bar else ""

        yield Static(f"\n▸ {title}")
        parts = [action]
        if entry is not None:
            parts.append(f"{t('analysis.entry_price')} {entry:.2f}")
        if size is not None:
            parts.append(f"{t('analysis.position_size')} ${size:.0f}")
        yield Static(f"  {'  '.join(parts)}{conf_str}")
        if reasoning:
            yield Static(f"  [dim]{reasoning}[/dim]")

    ops_comment = n.get("operations_commentary", "")
    if ops_comment:
        yield Markdown(ops_comment)

    # Position module
    thesis = n.get("thesis_status")
    if thesis:
        yield Static(f"\n\n── {t('analysis.section.position')} ──", classes="section-label")
        ts_icon = {"intact": "[green]✓[/green]", "weakened": "[yellow]~[/yellow]", "broken": "[red]✗[/red]"}.get(thesis, "?")
        yield Static(f"{t('analysis.thesis_label')} {ts_icon} {thesis}")
        tn = n.get("thesis_note", "")
        if tn:
            yield Static(f"  {tn}")
        sl = n.get("stop_loss")
        tp = n.get("take_profit")
        if sl is not None or tp is not None:
            parts = []
            if sl is not None:
                parts.append(_format_stop_loss_or_take_profit(
                    t("analysis.stop_loss"), sl,
                ))
            if tp is not None:
                parts.append(_format_stop_loss_or_take_profit(
                    t("analysis.take_profit"), tp,
                ))
            yield Static(f"  {'  '.join(parts)}")
        alt = n.get("alternative_market_id")
        if alt:
            yield Static(f"  {t('analysis.alternative')} {alt} {n.get('alternative_note', '')}")
        yield Static("")

    # Analysis
    analysis_text = n.get("analysis", "")
    if analysis_text:
        yield Static(f"\n── {t('analysis.section.analysis')} ──", classes="section-label")
        yield Markdown(analysis_text)
        ac = n.get("analysis_commentary", "")
        if ac:
            yield Markdown(ac)

    # Research
    findings = n.get("research_findings", [])
    if not findings:
        findings = n.get("supporting_findings", []) + n.get("invalidation_findings", [])
    if findings:
        yield Static(f"\n── {t('analysis.section.research')} ──", classes="section-label")
        research_md = ""
        for f in findings:
            if isinstance(f, dict):
                research_md += f"\n- {f.get('finding', '')}  *{f.get('source', '')} → {f.get('impact', '')}*"
        yield Markdown(research_md)
        rc = n.get("research_commentary", "") or n.get("evidence_commentary", "")
        if rc:
            yield Markdown(rc)

    # Risk
    risks = n.get("risk_flags", [])
    if risks:
        yield Static(f"\n── {t('analysis.section.risk')} ──", classes="section-label")
        risk_md = ""
        for rf in risks:
            if isinstance(rf, dict):
                sev = rf.get("severity", "info")
                text = rf.get("text", "")
                icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(sev, "·")
                risk_md += f"\n- {icon} {text}"
        yield Markdown(risk_md)
        rc = n.get("risk_commentary", "")
        if rc:
            yield Markdown(rc)

    # Summary
    summary = n.get("summary", "")
    if summary:
        yield Static(f"\n── {t('analysis.section.summary')} ──", classes="section-label")
        yield Markdown(summary)

    # Next steps
    yield Static(f"\n── {t('analysis.section.next')} ──", classes="section-label")
    nc = n.get("next_check_at")
    nr = n.get("next_check_reason", "")
    if nc:
        from datetime import datetime
        try:
            utc_dt = datetime.fromisoformat(nc)
            local_dt = utc_dt.astimezone()
            nc_local = local_dt.strftime("%m-%d %H:%M")
        except (ValueError, TypeError):
            nc_local = nc[:16]
        yield Static(f"\n{t('analysis.next_check_at')}  [cyan]{nc_local}[/cyan]  {nr}")


class LegacyAnalysisPanel(Widget):
    """v0.11.x JSON-narrative analysis panel with version selector.

    Kept for back-compat. The v0.12.0 entry point is `AnalysisPanel` in
    `analysis_panel.py`, which dispatches per-version on `narrative_format`
    and reuses `_compose_legacy_body` here for json-format rows.
    """

    DEFAULT_CSS = """
    LegacyAnalysisPanel { height: auto; }
    LegacyAnalysisPanel DashPanel { width: 1fr; margin: 0 1; height: auto; }
    LegacyAnalysisPanel .section-label { text-style: bold; color: $primary; padding: 1 0 0 1; }
    LegacyAnalysisPanel .row { padding: 0 0 0 1; }
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

        8+ Markdown widgets without stable IDs make per-widget update
        impractical. Recomposing LegacyAnalysisPanel itself is safe: the outer
        VerticalScroll is on EventDetailView (event_detail.py:175), and
        Textual's recompose is scoped to widget+descendants. The user's
        scroll position lives in the outer VerticalScroll and is preserved.
        """
        self._analyses = analyses
        self._version_idx = version_idx
        self._analyzing = analyzing
        if analyses and version_idx < 0:
            self._version_idx = len(analyses) - 1
        self.refresh(recompose=True)
