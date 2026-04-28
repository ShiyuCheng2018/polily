"""AnalysisPanel: AI analysis display with version selector."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Markdown, Static

from polily.tui.i18n import t
from polily.tui.widgets.cards import DashPanel

CONFIDENCE_BAR = {
    "low": "[red]██[/red][dim]██████[/dim]",
    "medium": "[yellow]█████[/yellow][dim]███[/dim]",
    "high": "[green]███████[/green][dim]█[/dim]",
}


class AnalysisPanel(Widget):
    """AI analysis panel with operations, research, risk, summary modules."""

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

        n = self._current_narrative()
        if n is None:
            return

        panel = DashPanel(id="panel-analysis")
        panel.border_title = t("analysis.title")
        with panel:
            yield from self._render_narrative(n)
            yield Static("")
            yield from self._render_version_selector()

    def _current_narrative(self) -> dict | None:
        if not self._analyses or self._version_idx < 0:
            return None
        v = self._analyses[self._version_idx]
        return v.narrative_output if v.narrative_output else None

    def _render_narrative(self, n: dict) -> ComposeResult:
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
                    parts.append(f"{t('analysis.stop_loss')} {sl:.2f}")
                if tp is not None:
                    parts.append(f"{t('analysis.take_profit')} {tp:.2f}")
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
