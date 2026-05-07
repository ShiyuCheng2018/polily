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

Returns Rich-compatible color tag: "green", "red", or "dim".
"""
from __future__ import annotations

import pytest

from polily.tui.formatters import GRAY, amount_color


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

    "green" / "red" are bare colors; "dim" is a Rich style modifier.
    All three are valid in Rich/Textual markup.
    """
    valid = {"green", "red", GRAY}
    for tx_type in ("BUY", "TOPUP", "WITHDRAW", "SELL", "RESOLVE", "FEE", "RESET"):
        for pnl in (None, 0.0, 1.0, -1.0):
            color = amount_color(tx_type, 0.0, pnl)
            assert color in valid, (
                f"amount_color returned {color!r} — not in {valid}"
            )


@pytest.mark.parametrize(
    "tx_type,amount,realized_pnl,expected_color",
    [
        # Wallet ledger view = cash-flow semantic
        # BUY ALWAYS gray (user-locked invariant 2026-05-07): position open, not P&L event
        ("BUY", -100.0, None, GRAY),
        ("BUY", -0.50, None, GRAY),
        # WITHDRAW / RESET also gray (user moves own money, no P&L)
        ("WITHDRAW", -50.0, None, GRAY),
        ("RESET", 0.0, None, GRAY),
        # TOPUP green (cash in + encourage capital adds)
        ("TOPUP", 100.0, None, "green"),
        # FEE red (real cost, regardless of view)
        ("FEE", -0.05, None, "red"),
        # SELL with positive cash flow → green even if realized_pnl is negative.
        # This is the v0.11.6 → v0.11.7 fix: SELL +$0.44 (亏本卖出 cash in)
        # was red under v0.11.6 P&L rule; now green under wallet ledger rule
        # because the *cash flow* is positive.
        ("SELL", 0.44, -7.68, "green"),
        # SELL with negative cash flow (rare; e.g., adjustments)
        ("SELL", -0.50, -7.68, GRAY),  # cash out from SELL is anomalous; gray = neutral
        # SELL with effectively zero cash flow → gray
        ("SELL", 0.001, -0.50, GRAY),
        ("SELL", 0.0, -0.50, GRAY),
        # RESOLVE with positive cash flow → green
        ("RESOLVE", 117.00, 16.37, "green"),
        ("RESOLVE", 0.44, -7.68, "green"),  # losing position resolved at zero
        # RESOLVE with zero cash flow → gray
        ("RESOLVE", 0.0, 0.0, GRAY),
        # Unknown tx_type fallback
        ("UNKNOWN", 100.0, None, GRAY),
    ],
)
def test_amount_color_wallet_ledger(tx_type, amount, realized_pnl, expected_color):
    """Wallet ledger uses cash-flow semantic; SELL/RESOLVE color tracks
    amount sign, NOT realized_pnl. BUY always gray (user-locked invariant)."""
    actual = amount_color(
        tx_type, amount, realized_pnl, view_mode="wallet_ledger",
    )
    assert actual == expected_color, (
        f"amount_color({tx_type!r}, {amount}, {realized_pnl}, "
        f"view_mode='wallet_ledger') = {actual!r}, expected {expected_color!r}"
    )


def test_amount_color_history_view_unchanged_from_v0_11_6():
    """History view (default) preserves v0.11.6 P&L rule. Existing
    test_amount_color cases above already cover this; this test is
    a smoke check that view_mode='history' is the default and
    matches v0.11.6 behavior."""
    # SELL with negative realized_pnl is RED (P&L impact rule)
    assert amount_color("SELL", 0.44, -7.68, view_mode="history") == "red"
    # SELL with positive realized_pnl is GREEN
    assert amount_color("SELL", 18.00, 2.46, view_mode="history") == "green"
    # Default value (no view_mode passed) must equal view_mode='history'
    assert amount_color("SELL", 0.44, -7.68) == amount_color(
        "SELL", 0.44, -7.68, view_mode="history",
    )


def test_amount_color_view_mode_buy_invariant():
    """BUY is gray in BOTH views. User-locked invariant 2026-05-07."""
    for vm in ("wallet_ledger", "history"):
        for amt in (-100.0, -0.50, 0.0, 100.0):
            assert amount_color("BUY", amt, None, view_mode=vm) == GRAY, (
                f"BUY must be gray under view_mode={vm!r} regardless of amount={amt}"
            )
