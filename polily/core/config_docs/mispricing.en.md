# Mispricing

Polily looks for two kinds of mispricing: (1) on crypto markets,
implied-vol probability distortion; (2) on multi-outcome markets,
whether mutually-exclusive outcome probabilities sum far from 1.0.
This section configures the trigger thresholds.

---

## mispricing.enabled

**Default true.** Master switch for mispricing detection. When off,
polily skips the entire mispricing module (scoring still runs, but the
mispricing card won't render).

**When to change it:** You want pure structural analysis (no interest in
pricing dislocations) → turn off. 99% of users should leave this alone.

---

## mispricing.crypto.volatility_lookback_days

**Default 30 days.** Rolling-window length for computing realized
volatility on the crypto underlying.

**When to change it:** You believe the last month's vol does NOT
represent the "normal regime" (e.g. right after a major event) →
shorten to 7–14 days so the model reacts faster to recent moves. But
small samples produce noisy estimates.

---

## mispricing.crypto.min_deviation_pct

**Default 0.08 (8%).** A Polymarket binary price must deviate from the
vol-implied price by more than this percentage to be flagged as
mispricing.

**When to change it:** Want more candidate mispricings → drop to 0.05.
Only want significant dislocations → raise to 0.15. Note: 8% may be
"normal noise" during crypto high-vol regimes and a "significant signal"
during low-vol regimes.

---

## mispricing.multi_outcome.enabled

**Default true.** Sub-switch for multi-outcome detection (requires
mispricing.enabled to also be on).

**When to change it:** You only care about crypto mispricing → turn
this off.

---

## mispricing.multi_outcome.max_sum_deviation

**Default 0.10.** On multi-outcome markets (e.g. election with many
candidates), all outcome `yes_price` values should sum near 1.0;
deviation beyond this threshold (i.e. sum < 0.9 or sum > 1.1) flags
mispricing.

**When to change it:** Want to catch small sum deviations → drop to
0.05. Only want significant ones → raise to 0.20. Note: sum deviation
= arbitrage opportunity, but execution has friction (fee + slippage);
0.10 is typically the lower bound where "after fees, still profitable"
holds.
