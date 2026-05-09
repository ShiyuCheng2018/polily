## 7. Per-Call Inputs

For each analysis, polily injects a YAML block at the **very top** of your prompt — above this manual, above the strategy, above the protocol footer. The block is the only thing that varies between dispatches; everything else is static for the polily release.

    language_directive: "<follow this output language strictly>"
    event_id: "<polymarket slug>"
    trigger: "<scan | movement | manual | scheduled>"
    timestamp_utc: "<UTC ISO 8601>"
    timestamp_local: "<local ISO 8601 with TZ>"
    has_position: <true | false>
    official_strategy_path: "<absolute path to packaged default.md>"
    position_summary: "<conditional — only when has_position=true>"

### Field semantics

- **`language_directive`** — a sentence telling you which output language to use, loaded from polily's i18n catalog (`language.directive_for_llm`). Reflects the user's current F2 toggle. Override the active strategy if it contradicts.
- **`event_id`** — Polymarket event slug. The single anchor for every DB query you write (`WHERE event_id = ?`).
- **`trigger`** — what caused this dispatch. See §2 for the full enum semantics.
- **`timestamp_utc`** / **`timestamp_local`** — both ISO 8601, both populated. Use UTC for DB queries (every polily column stores UTC); use local for narrating to the user (cf. §4 streaming-data convention).
- **`has_position`** — whether the user holds at least one position on a market under this event. Polily computes this fresh from the `positions` table at dispatch time; you can re-query for details (size, avg_cost, P&L) via SQL if needed.
- **`official_strategy_path`** — absolute filesystem path to polily's packaged `default.md`. Use the `Read` tool to load it for the §8 fallback flow. Don't hard-code package paths — pipx vs pip vs editable install puts the file in different places, and this field is the install-correct value.
- **`position_summary`** — appended **only when `has_position=true`** and the dispatcher had a summary string ready. Holds short-form position metadata (e.g. `"YES @ 0.42, qty 100, cost basis 0.38"`) so you don't need a `positions` SQL query for the common-case narration. Absent for `has_position=false`.

### Source-of-truth precedence

These fields override anything the active strategy says that contradicts. Examples:

- Strategy file says "always answer in English" but `language_directive` says respond in Chinese → use Chinese.
- Strategy file says "treat every event as no-position" but `has_position=true` → respect the actual position state.
- Strategy file references a hard-coded path to `default.md` → use `official_strategy_path` instead.

Treat the per-call block as **runtime state** that polily owns; the strategy is **methodology** that the user owns. When in conflict, runtime state wins.
