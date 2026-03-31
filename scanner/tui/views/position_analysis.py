"""PositionAnalysisView: dedicated view for position management analysis."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from scanner.agents.schemas import PositionAdvice


class BackFromPositionAnalysis(Message):
    """Return to paper status page."""
    pass


ADVICE_DISPLAY = {
    "hold": ("[green]HOLD[/green]", "继续持有"),
    "reduce": ("[yellow]REDUCE[/yellow]", "减仓"),
    "exit": ("[red]EXIT[/red]", "清仓"),
}


class PositionAnalysisView(Widget):
    """Dedicated position management analysis view."""

    BINDINGS = [
        Binding("escape", "go_back", "返回持仓"),
    ]

    DEFAULT_CSS = """
    PositionAnalysisView { height: 1fr; }
    PositionAnalysisView .section-title { text-style: bold; color: $primary; padding: 1 0 0 0; }
    PositionAnalysisView .detail-row { padding: 0 0 0 2; }
    PositionAnalysisView .finding-row { padding: 0 0 0 2; }
    PositionAnalysisView .finding-impact { padding: 0 0 0 4; color: $text-muted; }
    """

    def __init__(self, title: str, side: str, entry_price: float,
                 current_price: float, pnl_pct: float, days_held: float,
                 advice: PositionAdvice | None = None, loading: bool = False):
        super().__init__()
        self._title = title
        self._side = side
        self._entry_price = entry_price
        self._current_price = current_price
        self._pnl_pct = pnl_pct
        self._days_held = days_held
        self._advice = advice
        self._loading = loading

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(" [bold]持仓视角[/bold]", classes="section-title")
            yield Static(f"  {self._title}")
            yield Static(
                f"  {self._side.upper()} @ {self._entry_price:.2f} → "
                f"当前 {self._current_price:.2f} | "
                f"盈亏 {self._pnl_pct:+.1%} | "
                f"持仓 {self._days_held:.1f} 天"
            )

            if self._loading:
                yield Static("")
                yield Static("  AI 持仓分析中...", classes="detail-row")
            elif self._advice:
                yield from self._compose_advice(self._advice)
            else:
                yield Static("")
                yield Static("  [dim]分析失败[/dim]", classes="detail-row")

            yield Static("")
            yield Static("  [dim]Esc 返回持仓页[/dim]")

    def _compose_advice(self, a: PositionAdvice) -> ComposeResult:
        label, cn = ADVICE_DISPLAY.get(a.advice, ("[dim]?[/dim]", "?"))

        yield Static("")
        yield Static(f"  {label}  {a.reasoning}", classes="detail-row")

        # Thesis
        thesis_status = "[green]成立[/green]" if a.thesis_intact else "[red]不再成立[/red]"
        yield Static(f"  原有逻辑: {thesis_status}", classes="detail-row")
        if a.thesis_note:
            yield Static(f"  {a.thesis_note}", classes="detail-row")

        # Exit price
        if a.exit_price:
            yield Static(f"  建议价位: {a.exit_price}", classes="detail-row")

        # Risk
        if a.risk_note:
            yield Static(f"  ! {a.risk_note}", classes="detail-row")

        # Research findings
        findings = a.research_findings or []
        if findings:
            yield Static(" 研究发现", classes="section-title")
            for f in findings:
                if hasattr(f, "finding"):
                    source = f"[dim]{f.source}[/dim]" if f.source else ""
                    yield Static(f"  {f.finding}  {source}", classes="finding-row")
                    if f.impact:
                        yield Static(f"    -> {f.impact}", classes="finding-impact")

    def action_go_back(self) -> None:
        self.post_message(BackFromPositionAnalysis())
