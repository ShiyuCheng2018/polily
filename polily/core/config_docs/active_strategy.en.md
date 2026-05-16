# Active Strategy

Selects which strategy the polily NarrativeWriter agent uses when
producing analyses. Strategies are not knobs — they are the high-level
analytical posture (asymmetric stop-loss bias, vol-arb focus, custom
output sections) the agent applies on top of raw price + structure data.

---

## active_strategy

**Default `"official"`.** Which strategy text to load before each
NarrativeWriter dispatch.

**Values:**
- `"official"` — uses polily's packaged default strategy
  (`polily/strategies/default.md`)
- `"user"` — uses the markdown text stored in the `user_strategy` table,
  edited via the TUI 策略 page (key `7`)

**Hot-swap:** Toggling this takes effect on the next analysis dispatch;
analyses already in flight finish with the previously-selected strategy.

**When to switch to `"user"`:** Once you have a specific analytical
preference you want the agent to follow consistently — e.g. a focus on
information edge over vol arb, asymmetric position-sizing rules, or a
custom output format that the official strategy does not produce.

**Tip:** Until you have a clear preference, leave this on `"official"`.
The packaged strategy is the baseline polily is benchmarked against.
