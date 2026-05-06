"""Tests for polily.tui.formatters.amount_color — v0.11.6 Item 2.

Color rule changes from "现金流方向" → "P&L impact":

| Event | Color |
|---|---|
| BUY | gray (position open, no realized P&L) |
| TOPUP | green (positive psychology) |
| WITHDRAW | gray (user moving own money out) |
| SELL/RESOLVE realized > +$0.005 | green |
| SELL/RESOLVE realized < -$0.005 | red |
| SELL/RESOLVE abs(realized) < $0.005 | gray |
| FEE | red |
| RESET | gray |

Returns Rich-compatible color tag: "green", "red", or "$text-muted".
"""
from __future__ import annotations

import pytest

from polily.tui.formatters import amount_color

GRAY = "$text-muted"


@pytest.mark.parametrize(
    "tx_type,amount,realized_pnl,expected_color",
    [
        # Position-open / capital-flow events
        ("BUY", -100.0, None, GRAY),         # money out, but no P&L — gray not red
        ("TOPUP", 100.0, None, "green"),      # user added capital — encourage
        ("WITHDRAW", -50.0, None, GRAY),      # user took own money — neutral
        ("RESET", 0.0, None, GRAY),           # bookkeeping
        # FEE — always a real cost
        ("FEE", -0.05, None, "red"),
        # SELL with material gain
        ("SELL", 18.00, 2.46, "green"),
        # SELL with material loss
        ("SELL", 5.00, -7.68, "red"),
        # RESOLVE with material gain
        ("RESOLVE", 117.00, 16.37, "green"),
        # RESOLVE with material loss
        ("RESOLVE", 0.00, -2.29, "red"),
        # Zero-magnitude P&L cases
        ("SELL", 0.001, 0.001, GRAY),         # below $0.005 threshold
        ("SELL", -0.001, -0.001, GRAY),       # below threshold (was red pre-v0.11.6)
        ("RESOLVE", 0.0, 0.0, GRAY),          # exactly zero
        # Boundary: 0.005 is at-or-above the gray threshold (rule is
        # `abs(realized) < 0.005` for gray), so 0.005 → green not gray.
        # See test_amount_color_threshold_exact_005 for the explicit boundary.
        # SELL/RESOLVE with realized_pnl=None (defensive — shouldn't happen, but safe)
        ("SELL", 100.0, None, GRAY),
        # Unknown tx_type — gray fallback
        ("UNKNOWN", 100.0, None, GRAY),
        ("", 0.0, None, GRAY),
    ],
)
def test_amount_color(tx_type, amount, realized_pnl, expected_color):
    """Parametrized table of all color-decision cases."""
    actual = amount_color(tx_type, amount, realized_pnl)
    assert actual == expected_color, (
        f"amount_color({tx_type!r}, {amount}, {realized_pnl}) "
        f"= {actual!r}, expected {expected_color!r}"
    )


def test_amount_color_threshold_exact_005():
    """Boundary: realized_pnl = exactly +0.005 should be green (NOT gray).

    The rule is `abs(realized_pnl) < 0.005` for gray. So 0.005 is on the
    "real gain" side; 0.0049 is gray.
    """
    assert amount_color("SELL", 0.01, 0.005) == "green"
    assert amount_color("SELL", 0.01, 0.0049) == GRAY
    assert amount_color("SELL", -0.01, -0.005) == "red"
    assert amount_color("SELL", -0.01, -0.0049) == GRAY


def test_amount_color_returns_rich_compatible_tags():
    """Returned values must work as Rich color tags: f"[{color}]...[/{color}]".

    "green" / "red" are bare colors. "$text-muted" is a Textual theme
    variable. All three are valid in Rich/Textual markup.
    """
    valid = {"green", "red", GRAY}
    for tx_type in ("BUY", "TOPUP", "WITHDRAW", "SELL", "RESOLVE", "FEE", "RESET"):
        for pnl in (None, 0.0, 1.0, -1.0):
            color = amount_color(tx_type, 0.0, pnl)
            assert color in valid, (
                f"amount_color returned {color!r} — not in {valid}"
            )
