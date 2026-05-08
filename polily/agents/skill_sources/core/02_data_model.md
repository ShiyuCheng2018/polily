## 2. Polily Mechanics

Polily is structured around two domain concepts:

- **Event** (`events` table): a Polymarket event identified by a slug. An event has metadata (title, end_date, neg_risk flag, score_breakdown) and one or more child markets.
- **Market** (`markets` table): a single tradable outcome under an event. Each market has yes_price / no_price / volume and lifecycle state (closed, resolved_outcome).

**negRisk events** have multiple mutually-exclusive markets summing to ~1.0 (winner-take-all). For these, the score_breakdown JSON includes `implied_fair_value` per market — the implied price under the negRisk completeness identity (1 − Σ(other markets' yes_price)).

**Daemon poll cycle**: a single global poll job runs every 30s on a dedicated executor. It fetches prices for every market in the user's monitoring set, records movement signals, and dispatches AI analyses when scan_logs.next_check_at is due.

**Trigger sources** for analyses: `scan` (initial scoring of a freshly-pasted URL), `movement` (significant price movement detected), `manual` (user clicked "AI analysis" in TUI).

**Scoring (5-dim)**: each event carries a 0–100 structure score combining spread, depth, objectivity, time-to-close, and friction. Score is *tradability*, not *trade quality* — never confuse the two when narrating.
