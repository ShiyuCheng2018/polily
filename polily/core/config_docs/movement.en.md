# Movement Triggers

This section is the core of how polily decides "something happened on
this market that's worth an AI analysis." Every knob influences the
daemon's Step 3.5 dispatcher and the movement scorer.

Higher thresholds → more conservative, fewer AI calls. Lower
thresholds → more aggressive, more AI usage.

> **About terminology in the `movement.weights.*` subtree:** the 26
> weight leaves only carry the signal name (e.g. `price_z_score`) in
> their markdown description; full semantics live in the
> `_signals_glossary` block below — to avoid repeating the same
> definition across 4 market types × multiple signals. The loader skips
> sections starting with `_`, so `_signals_glossary` does NOT register
> as an editable leaf in the TUI. It's purely a developer reference.

---

## _signals_glossary

Defines every signal used by the weights subtree. Each weight leaf's
short description points back to the term entry here; come here when
you want to know what a signal actually measures. Underscore-prefixed
sections are skipped by the loader, so this block does NOT register as
a TUI config knob — it's documentation, not configuration.

### price_z_score
Standard-deviation distance of the current price from a recent rolling
window. > 2 σ flagged as a regime shift.

### book_imbalance
Order-book bid/ask size ratio (bid_size / ask_size). > 3 flagged as
one-sided pressure.

### fair_value_divergence
Percentage deviation of the current price from fair value (where fair
value is computed from the underlying price + time decay). Crypto
markets only.

### underlying_z_score
Z-score of the underlying (e.g. BTC, ETH); crypto markets only.

### cross_divergence
Cross-asset divergence signal; crypto markets only (e.g. BTC-PERP vs
the Polymarket BTC binary).

### sustained_drift
Strength of sustained one-directional price drift; political markets
only.

### time_decay_adjusted_move
Price move adjusted for time decay; economic_data markets only.

### volume_ratio
Multiple of the current volume over the recent rolling-window mean.

### trade_concentration
Largest single trade as a fraction of total volume; high values mean
"a few big orders are pushing the market."

### volume_price_confirmation
Correlation between volume and price movement.

---

## movement.magnitude_threshold

**Default 70.** A movement's "magnitude score" (0–100) must clear this
threshold to be treated as "potentially important." The magnitude score
combines price z-score, book imbalance, fair-value divergence, etc.
(weighted per market type — see the weights subtree).

**Where 70 came from:** during v0.7 we observed that 80%+ of movements
below 70 were noise. It's the experimental balance between "AI fires on
noise too often vs. AI misses real signals."

**How to tune:** drop to 50–60 if you want AI to engage more often;
raise to 80+ for extreme conservatism. Lowering meaningfully increases
daemon AI-call volume — watch the cost.

---

## movement.quality_threshold

**Default 60.** Used in series with `magnitude_threshold` — AI is only
triggered when **both** scores clear their gates. The quality score
measures "how clean the signal is" (volume confirmation, single-trade
concentration, volume-price agreement).

**Why two gates:** a large price swing (high magnitude) on thin volume
(low quality) may be a single-order noise move, not worth AI analysis.

**How to tune:** lower quality if you want polily to analyze "violent
but isolated" moves; raise it so polily only steps in when the move is
"violent and broad."

---

## movement.daily_analysis_limit

**Default 10.** Maximum number of AI analyses fired per market per day.
Prevents a single hyper-active market from re-tripping
magnitude/quality thresholds and exploding AI usage.

**When to change it:** if you want to see every analysis for hot
markets that hit 10/day → raise to 20–30. Drop to 1–3 for extreme
cost-sensitive scenarios.

---

## movement.min_history_entries

**Default 5.** A market needs at least this many `movement_log` rows
before scoring kicks in. Below this count the score computation is
skipped (insufficient data, z-score is unreliable).

**When to change it:** rarely needed. If you feel polily is "too slow
to start analyzing" newly-added events, lower to 3 — but z-score gets
noisy below 3 samples.

---

## movement.stale_threshold_seconds

**Default 600 seconds (10 minutes).** `movement_log` data older than
this is treated as stale and skipped. Prevents the daemon from
triggering analyses against expired data.

**When to change it:** if you want polily to keep trusting older data
across a long network/poll outage, raise to 1800 (30 min) or 3600
(1 hour). Below 60 seconds, with a 30-second poll interval, you'll
skip a lot of score computations.

---

## movement.weights.crypto.magnitude.price_z_score

**Default 0.15.** This signal is weighted lightly on crypto — thin
liquidity produces many false breakouts; we lean more on
`fair_value_divergence` (0.40).
See [glossary → price_z_score](#price_z_score).

## movement.weights.crypto.magnitude.book_imbalance

**Default 0.10.** Crypto book liquidity is often thin, so book-imbalance
signals are noisy.
See [glossary → book_imbalance](#book_imbalance).

## movement.weights.crypto.magnitude.fair_value_divergence

**Default 0.40.** The most important magnitude signal on crypto —
divergence from fair value (underlying price + time decay) is polily's
primary mispricing signal in this category.
See [glossary → fair_value_divergence](#fair_value_divergence).

## movement.weights.crypto.magnitude.underlying_z_score

**Default 0.20.** A z-score breakout on the underlying (BTC/ETH) is an
early indicator of price reaction in crypto markets.
See [glossary → underlying_z_score](#underlying_z_score).

## movement.weights.crypto.magnitude.cross_divergence

**Default 0.15.** Divergence between the Polymarket binary and the perp
market; moderate weight to avoid being dominated by violent perp
swings.
See [glossary → cross_divergence](#cross_divergence).

## movement.weights.crypto.quality.volume_ratio

**Default 0.40.** Whether volume actually expanded is the strongest
"is this real?" signal on crypto.
See [glossary → volume_ratio](#volume_ratio).

## movement.weights.crypto.quality.trade_concentration

**Default 0.35.** Whether a few large trades are pushing the move;
single-block trades are common on crypto but still warrant attention.
See [glossary → trade_concentration](#trade_concentration).

## movement.weights.crypto.quality.volume_price_confirmation

**Default 0.25.** Volume-price agreement; moderate weight to balance
the volume signal.
See [glossary → volume_price_confirmation](#volume_price_confirmation).

## movement.weights.political.magnitude.price_z_score

**Default 0.35.** Political-market books are stable, so a z-score
breakout more reliably reflects genuine information flow; weighted
higher than on crypto.
See [glossary → price_z_score](#price_z_score).

## movement.weights.political.magnitude.book_imbalance

**Default 0.25.** Political books are more trustworthy than crypto, so
book imbalance is a meaningful signal.
See [glossary → book_imbalance](#book_imbalance).

## movement.weights.political.magnitude.sustained_drift

**Default 0.40.** The most important magnitude signal on political —
sustained one-directional drift typically corresponds to "a real event
happening" (poll, statement, leak).
See [glossary → sustained_drift](#sustained_drift).

## movement.weights.political.quality.volume_ratio

**Default 0.35.** A political move accompanied by volume expansion is a
trustworthy signal.
See [glossary → volume_ratio](#volume_ratio).

## movement.weights.political.quality.trade_concentration

**Default 0.40.** Large single trades on political markets often signal
"informed parties moving first"; weighted higher than on crypto.
See [glossary → trade_concentration](#trade_concentration).

## movement.weights.political.quality.volume_price_confirmation

**Default 0.25.** Volume-price agreement; same weight as on crypto.
See [glossary → volume_price_confirmation](#volume_price_confirmation).

## movement.weights.economic_data.magnitude.price_z_score

**Default 0.30.** Economic-data markets (CPI, jobs, etc.) sit between
crypto and political in terms of book behavior.
See [glossary → price_z_score](#price_z_score).

## movement.weights.economic_data.magnitude.book_imbalance

**Default 0.15.** Economic-data book liquidity is often modest;
moderate weight.
See [glossary → book_imbalance](#book_imbalance).

## movement.weights.economic_data.magnitude.time_decay_adjusted_move

**Default 0.55.** The most important magnitude signal on economic_data
— release timing is known up front, so a price move adjusted for time
decay directly reflects how the print deviates from expectations.
See [glossary → time_decay_adjusted_move](#time_decay_adjusted_move).

## movement.weights.economic_data.quality.volume_ratio

**Default 0.40.** A clear volume bump around release time is the core
quality signal here.
See [glossary → volume_ratio](#volume_ratio).

## movement.weights.economic_data.quality.trade_concentration

**Default 0.30.** Single-trade concentration on economic_data is lower
than on political (more dispersed retail participation).
See [glossary → trade_concentration](#trade_concentration).

## movement.weights.economic_data.quality.volume_price_confirmation

**Default 0.30.** Volume-price agreement; same weight across other
market types.
See [glossary → volume_price_confirmation](#volume_price_confirmation).

## movement.weights.default.magnitude.price_z_score

**Default 0.45.** "default" is the fallback when polily can't identify
the market type. The highest-weighted magnitude signal is z-score — the
most generic, least dependent on type-specific data.
See [glossary → price_z_score](#price_z_score).

## movement.weights.default.magnitude.book_imbalance

**Default 0.30.** Book imbalance is the second-most-important magnitude
signal in the fallback case.
See [glossary → book_imbalance](#book_imbalance).

## movement.weights.default.magnitude.volume_ratio

**Default 0.25.** In the fallback case, magnitude also uses
`volume_ratio` (other market types put this in quality only) — because
default doesn't know which quality signals are particularly important,
the magnitude/quality boundary is fuzzier here.
See [glossary → volume_ratio](#volume_ratio).

## movement.weights.default.quality.volume_ratio

**Default 0.40.** The fallback quality side also leans on
`volume_ratio` — and there's no clash with magnitude's `volume_ratio`:
the magnitude version measures "did volume expand?", while the quality
version measures "is the expansion trustworthy?" (different rolling-
window references).
See [glossary → volume_ratio](#volume_ratio).

## movement.weights.default.quality.trade_concentration

**Default 0.35.** `trade_concentration` keeps the same weight in
fallback quality as in other market types.
See [glossary → trade_concentration](#trade_concentration).

## movement.weights.default.quality.volume_price_confirmation

**Default 0.25.** `volume_price_confirmation` keeps the same weight in
fallback quality as in other market types.
See [glossary → volume_price_confirmation](#volume_price_confirmation).
