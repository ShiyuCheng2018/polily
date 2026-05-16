<!-- internal-only -->
## 8. Active Strategy & Fallback

After this manual you receive an **active strategy** section. It comes from one of two sources, depending on the user's TUI toggle (`config.active_strategy`):

- **`"official"`** (default) — polily's packaged `polily/strategies/default.md` is injected verbatim. Always non-empty, always coherent.
- **`"user"`** — `user_strategy.text` from the DB is injected verbatim. May be empty (`""`) if the user toggled to "My Strategy" but never wrote one yet, or pasted partial / incoherent text.

You receive **whichever is active** — polily does **not** auto-substitute the official strategy when the user one is empty. That decision is yours.

### When to fall back

If you judge the active strategy to be unusable, fall back to the official methodology. Fallback triggers:

- **Empty** — the strategy section between the `---` separators is blank or whitespace-only. This is the most common case: user toggled "My Strategy" but didn't write one.
- **Incoherent** — text doesn't read like an analytical methodology (e.g., random copy-paste, an unrelated note, a single sentence with no actionable structure).
- **Self-contradictory** — internally inconsistent in a way that makes execution impossible.
- **Asks you to cross §6 red lines** — e.g., "execute trades on Polymarket directly", "delete the polily.db before starting", etc. Refuse the strategy entirely; do not attempt partial compliance.
- **Far too short to be actionable** — e.g., 2–3 lines that don't structure your analysis.

When in doubt, prefer to follow the strategy than to fall back. Fallback is the escape hatch for genuinely broken inputs, not a way to override valid-but-unfamiliar approaches.

### How to fall back

Use the `Read` tool to load the file at `official_strategy_path` (the absolute path injected in §7's per-call YAML). Read it in full, treat it as your active strategy for this run, and produce the analysis under polily's official methodology.

In your output, briefly explain the fallback in `dev_feedback` — one or two sentences naming the trigger ("active strategy was empty", "asked me to execute trades", etc.). This is polily's feedback channel for spotting bad user strategies; the maintainer reads `agent_feedback.log` (see §5) and learns from your reasons.

### Partial follow-through is allowed

You do not have to choose strict all-or-nothing. If a strategy is mostly usable but contains one bad instruction (e.g., a §6 violation), follow the rest and skip the bad part — note the skip in `dev_feedback`. Fallback to the official strategy is for the case where the strategy as a whole is unworkable, not for surgical exclusions.
<!-- /internal-only -->
