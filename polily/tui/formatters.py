"""Shared TUI formatting helpers.

v0.11.6 Item 2 introduces `amount_color()` — the single source of truth
for wallet ledger + 已实现交易历史 row coloring. Both views consume
this helper; future shared formatters land here too.
"""
from __future__ import annotations

from typing import Literal

# Tag used for "neutral" rows. The plan originally specified Textual's
# `$text-muted` CSS variable, but that token is rejected by Rich's
# markup parser (`[$text-muted]…[/$text-muted]` fails with MarkupError).
# `dim` is a Rich style modifier that renders identically across light
# and dark themes and was already in use by the legacy wallet view.
GRAY = "dim"


def amount_color(
    tx_type: str,
    amount: float,
    realized_pnl: float | None,
    view_mode: Literal["wallet_ledger", "history"] = "history",
) -> str:
    """Return Rich-compatible color tag for a wallet/history row.

    Two view semantics (v0.11.7):

    - **history (P&L impact)** [default]: color reflects realized P&L sign.
      BUY → gray; TOPUP → green; FEE → red; SELL/RESOLVE colored by
      `realized_pnl`; near-zero gray. This is the v0.11.6 default,
      preserved for the 已实现交易历史 view where each row is a
      P&L-completed trade.

    - **wallet_ledger (cash-flow direction)**: color reflects amount sign,
      NOT P&L. SELL/RESOLVE with positive cash flow is green even if
      realized_pnl is negative — wallet ledger is a cash-flow account,
      not a P&L account. The 流水 view answers "money in/out", not
      "trade win/loss".

    **Invariant across both views:** BUY is ALWAYS gray. Position-opening
    is not a P&L event regardless of which lens you read the row through.
    User-locked 2026-05-07.

    Returns one of: "green", "red", "dim".
    """
    # Universal: BUY/WITHDRAW/RESET → gray (no P&L event); FEE → red
    # (real cost); TOPUP → green (encourage capital adds). These hold in
    # both view modes.
    if tx_type == "TOPUP":
        return "green"
    if tx_type in ("BUY", "WITHDRAW", "RESET"):
        return GRAY
    if tx_type == "FEE":
        return "red"

    # SELL / RESOLVE: view-mode-dependent.
    if tx_type in ("SELL", "RESOLVE"):
        if view_mode == "wallet_ledger":
            # Cash-flow semantic: track amount sign.
            if amount is None or abs(amount) < 0.005:
                return GRAY
            return "green" if amount > 0 else GRAY
        # history (default): P&L semantic.
        if realized_pnl is None or abs(realized_pnl) < 0.005:
            return GRAY
        return "green" if realized_pnl > 0 else "red"

    return GRAY  # unknown tx_type — safe default
