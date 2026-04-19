"""Movement status — shows latest event-level movement (M/Q + label)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from scanner.tui.monitor_format import pick_movement_color

_LABEL_CN = {
    "consensus": "共识异动",
    "whale_move": "大单异动",
    "slow_build": "缓慢累积",
    "noise": "平静",
}


def get_event_movement(movements: list[dict]) -> tuple[float, float, str]:
    """Get event-level movement: max(M), max(Q), best label across latest tick.

    Returns (magnitude, quality, label).
    """
    if not movements:
        return 0, 0, "noise"

    # Latest tick = entries sharing the most recent created_at (within 60s)
    market_entries = [e for e in movements if e.get("market_id") is not None]
    if not market_entries:
        return 0, 0, "noise"

    latest_ts = market_entries[0].get("created_at", "")[:19]  # trim to second
    # Take all entries within same tick (same second)
    tick_entries = [
        e for e in market_entries
        if e.get("created_at", "")[:19] == latest_ts
    ]
    if not tick_entries:
        tick_entries = market_entries[:1]

    m = max((e.get("magnitude", 0) or 0) for e in tick_entries)
    q = max((e.get("quality", 0) or 0) for e in tick_entries)

    # Label from highest-scoring entry
    best = max(tick_entries, key=lambda e: (e.get("magnitude", 0) or 0) + (e.get("quality", 0) or 0))
    label = best.get("label", "noise")

    return m, q, label


class MovementSparkline(Widget):
    """Simple movement status display: M/Q values + label."""

    DEFAULT_CSS = """
    MovementSparkline {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        movements: list[dict],
        markets: list | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._movements = movements or []
        self._markets = markets or []

    def compose(self) -> ComposeResult:
        m, q, label = get_event_movement(self._movements)
        label_cn = _LABEL_CN.get(label, label)
        color = pick_movement_color(label, m)

        if label == "noise":
            yield Static(f"[bold]异动[/]  [{color}]{label_cn}[/{color}]  [dim]M:{m:.0f} Q:{q:.0f}[/dim]")
        else:
            yield Static(f"[bold]异动[/]  [{color}]{label_cn}[/{color}]  M:{m:.0f} Q:{q:.0f}")
