"""BinaryMarketStructurePanel — 5-dimension score panel for binary events.

Binary events have a single market, so `SubMarketTable` (which renders only
when `len(markets) > 1`) skips them. This panel fills the gap: it shows the
same per-dimension score breakdown + commentary that multi-market events
expose via row expansion, but laid out flat.
"""

from __future__ import annotations

import contextlib
import json as _json

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from polily.tui.i18n import t
from polily.tui.widgets.cards import DashPanel

# Internal dim keys (canonical, used in score_breakdown JSON) → catalog keys.
# Labels are looked up via t() at compose time so they flip on language switch.
_DIM_KEYS = ["liquidity", "verifiability", "probability", "time", "friction"]

_BAR_WIDTH = 15


class BinaryMarketStructurePanel(Widget):
    """Renders the single market's structure score dimensions as a flat panel."""

    DEFAULT_CSS = """
    BinaryMarketStructurePanel { height: auto; margin: 0 1; }
    BinaryMarketStructurePanel DashPanel { width: 1fr; height: auto; }
    BinaryMarketStructurePanel .dim-row { padding: 0 0 0 1; }
    BinaryMarketStructurePanel .overall-row { padding: 1 0 0 1; text-style: bold; }
    BinaryMarketStructurePanel .empty-row { padding: 0 0 0 1; }
    """

    def __init__(self, market, event=None):
        super().__init__()
        self._market = market
        self._event = event

    def compose(self) -> ComposeResult:
        panel = DashPanel()
        panel.border_title = t("binary_structure.title")
        with panel:
            bd = self._parse_breakdown()
            if not bd:
                yield Static(f"[dim]{t('binary_structure.empty')}[/dim]", classes="empty-row")
                return

            weights = self._resolve_weights()
            commentary = bd.get("commentary") or {}
            dim_comments = commentary.get("dim_comments") or {}

            dims = [(t(f"scoring.dim.{k}"), k) for k in _DIM_KEYS]
            if weights.get("net_edge", 0) > 0:
                # 'Edge' kept untranslated (canonical scoring term).
                dims.append(("Edge", "net_edge"))

            for label, key in dims:
                val = float(bd.get(key, 0) or 0)
                max_w = float(weights.get(key, 0) or 0)
                bar = self._bar(val, max_w)
                comment = dim_comments.get(key, "")
                yield Static(
                    f"{label:<6} {bar} {val:>4.0f}/{max_w:<3.0f}  [dim]{comment}[/dim]",
                    classes="dim-row",
                )

            overall = commentary.get("overall") or ""
            if overall:
                yield Static(f"[b]{t('binary_structure.overall')}:[/b] {overall}", classes="overall-row")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_breakdown(self) -> dict | None:
        raw = getattr(self._market, "score_breakdown", None)
        if not raw:
            return None
        with contextlib.suppress(ValueError, TypeError):
            bd = _json.loads(raw)
            if isinstance(bd, dict):
                return bd
        return None

    def _resolve_weights(self) -> dict:
        from polily.scan.scoring import _DEFAULT_WEIGHTS, _TYPE_WEIGHTS

        mtype = getattr(self._market, "market_type", None) or "other"
        if mtype == "other" and self._event is not None:
            mtype = getattr(self._event, "market_type", None) or "other"
        return _TYPE_WEIGHTS.get(mtype, _DEFAULT_WEIGHTS)

    @staticmethod
    def _bar(val: float, max_w: float) -> str:
        if max_w <= 0:
            return "░" * _BAR_WIDTH
        filled = int(min(val, max_w) / max_w * _BAR_WIDTH)
        return "█" * filled + "░" * (_BAR_WIDTH - filled)
