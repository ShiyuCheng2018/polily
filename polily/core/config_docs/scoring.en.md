# Scoring

Polily scores each event 0–100 (structure score), then bins by threshold
into tier A / B / C: A = strong candidate, B = alternate, C = skip. This
section configures the tier boundaries.

Note: per-dimension weights (liquidity / verifiability / probability
space / time / friction) live as module constants in
`polily/scan/scoring.py` — tightly coupled to the scoring algorithm,
intentionally not user-editable.

---

## scoring.thresholds.tier_a_min_score

**Default 70.** Events with a total ≥ 70 → tier A (strong candidate).

**When to change it:** Want to see more events promoted to A (accepting
some quality drop) → lower to 60. Want extreme strictness, only top
events → push to 80+.

---

## scoring.thresholds.tier_b_min_score

**Default 45.** Events with a total in [45, 70) → tier B (alternate).
Below 45 → tier C (hidden from the main view, archived).

**When to change it:** Too many tier C events showing up → raise to 50
so borderline events fall to C. Want to catch more long-tail picks →
drop to 35–40, but polily's scans will get noisier.

---

## scoring.thresholds.tier_a_require_mispricing

**Default false.** Whether tier A demands a mispricing signal (crypto
vol / multi-outcome max-sum) in addition to a high structure score.

**Why off by default:** not every polily user's edge comes from
mispricing — some edges are structural (deep books + low friction).
Turning this on requires tier A events to have BOTH a structural edge
AND a pricing edge — stricter filter, but may miss pure-structure
opportunities.

**When to change it:** Your strategy is mispricing-driven → turn it on,
cleaner filter. Your strategy accepts structural-only events (even
without a pricing dislocation) → leave off (default).
