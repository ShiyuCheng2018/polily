"""Shared TUI formatting helpers.

v0.11.6 Item 2 introduces `amount_color()` — the single source of truth
for wallet ledger + 已实现交易历史 row coloring. Both views consume
this helper; future shared formatters land here too.
"""
from __future__ import annotations

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
) -> str:
    """Return Rich-compatible color tag for a wallet/history row.

    Rule (v0.11.6): color reflects P&L impact, NOT cash flow direction.
    Pre-v0.11.6 used cash flow direction, which painted BUY red — but
    BUY is just opening a position, not a realized loss. New rule:

      BUY                              → gray (position open)
      TOPUP                            → green (encourage capital add)
      WITHDRAW                         → gray (user moving own money)
      RESET                            → gray (bookkeeping)
      FEE                              → red (real cost)
      SELL/RESOLVE realized > +$0.005  → green (real gain)
      SELL/RESOLVE realized < -$0.005  → red (real loss)
      SELL/RESOLVE |realized| < $0.005 → gray (effectively zero)
      unknown tx_type                  → gray (safe default)

    Args:
        tx_type: wallet_transactions.type — one of BUY/SELL/TOPUP/
            WITHDRAW/RESOLVE/FEE/RESET (per polily/core/wallet.py
            _CREDIT_TX_TYPES + the wallet view's _format_tx_description).
        amount: signed dollar amount (currently unused — kept in
            signature for future rules that want it).
        realized_pnl: realized P&L for SELL/RESOLVE; None for other
            tx_types (matches the wallet_transactions schema).

    Returns:
        One of: "green", "red", "dim". All three are valid Rich/Textual
        color markup tokens.
    """
    if tx_type == "TOPUP":
        return "green"
    if tx_type in ("BUY", "WITHDRAW", "RESET"):
        return GRAY
    if tx_type == "FEE":
        return "red"
    if tx_type in ("SELL", "RESOLVE"):
        if realized_pnl is None or abs(realized_pnl) < 0.005:
            return GRAY
        return "green" if realized_pnl > 0 else "red"
    return GRAY  # unknown type — safe default
