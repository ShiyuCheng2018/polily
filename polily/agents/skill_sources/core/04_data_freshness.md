## 4. Data Freshness

Polily exposes data with four distinct freshness profiles. Knowing which is which prevents you from over-trusting a stale value or wasting time re-querying a fresh stream.

1. **Real-time stream** — `markets.yes_price`, `markets.no_price`, `markets.volume`, `markets.last_updated`. Updated every 30s by the global poll job. If you query the same row 5 seconds apart you may see different values; that is correct, not a race condition.

2. **Periodic computed** — `events.structure_score`, `events.score_breakdown` (incl. negRisk `implied_fair_value`). Recomputed each daemon score-refresh cycle (typically every poll). Lags real-time prices by up to ~30s.

3. **External API at analysis time** — claude CLI calls (other AI agents), web search, Binance ccxt for crypto vol fairness. These run only inside your current analysis session; the cost is non-trivial — call them when needed, not by default.

4. **Static** — `events.event_metadata.context_description`, table schemas, polily mechanics. Set at scan time or doesn't change.

When you observe a value changing across two reads in the same analysis, it is almost always a real-time stream (bucket 1) — not a polily bug. Mention this in your narrative if it materially affected your reasoning.
