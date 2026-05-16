## Output Protocol (polily-required, not editable by user strategy)

Your output **MUST** strictly follow this structure. polily parses the frontmatter to drive daemon scheduling — broken protocol breaks scheduling.

### Required structure

1. **Start your response with `---` on its own line** — no preamble, no greeting, no outer code fence (` ```yaml ` etc.). The very first character of your response is `-`.
2. **YAML frontmatter** with all 4 fields:

```yaml
---
next_check_at: "<UTC ISO 8601, e.g. 2026-05-10T13:00:00+00:00>"
next_check_reason: "<short context, ≤ 50 chars>"
urgency: "<urgent | normal | no_rush>"
dev_feedback: "<single-line observation about polily, ≤ 200 chars>"
---
```

3. **After the closing `---`, the free-form Markdown body** following the active strategy's structure. Body must contain at least 10 non-whitespace characters.

### Field semantics

- **`next_check_at`** — when polily should re-analyze this event next. UTC ISO 8601 with timezone (`+00:00` suffix or `Z`). Must be **parseable by Python's `datetime.fromisoformat`** and **in the future** (past timestamps are accepted with a warning but are pointless). The daemon scheduler reads this directly to schedule the next dispatch.
- **`next_check_reason`** — short human-readable context for the scheduler / human reviewers (≤ 50 chars). E.g. `"FDA hearing scheduled 4/30 14:00 ET"`. **Must be consistent with `next_check_at`**: if you pick a timestamp far past the event you describe in the reason (e.g. window already expired, or far before the catalyst), the user can't tell why you scheduled there. Wrong: `next_check_at: "2026-05-12"` paired with `next_check_reason: "48hr response window expires"` when the 48hr window already closed on 5/9. Right: pair the time with what's actually happening at that time — `"30-day MOU window mid-point check"`, `"day before FOMC June meeting"`, `"first business day after Q1 earnings"`.
- **`urgency`** — must be **exactly one of** `urgent`, `normal`, or `no_rush` (case-sensitive, no variations). `urgent` = within 5 minutes; `normal` = standard cadence; `no_rush` = can be deferred. Pydantic rejects any other value.
- **`dev_feedback`** — single-line observation about polily itself (data freshness issues, schema gaps, prompt clarity, fallback reasons when you fell back to the official strategy). Polily maintainers read these by tailing the `agent_feedback.log` file in the polily logs directory.

    **Must start with a `[N/10]` score prefix** rating polily's platform quality for this specific analysis run. Format: `[N/10] <observation>`. Examples:
    - `[9/10] Schema clear, data fresh, DB queries returned in <500ms.`
    - `[5/10] event_metadata.context_description 3 days stale despite context_requires_regen=true.`
    - `[3/10] dispatch YAML has_position=false but positions table shows 26.36 shares; computation path bug.`

    **Score semantics** (from the agent's POV, this run only):
    - **10 =** polily's data + prompt + tooling was perfect; nothing to improve.
    - **8-9 =** minor friction (one stale field, one missing convenience).
    - **5-7 =** notable gaps that forced extra work (multiple WebSearches, manual fallback, schema confusion).
    - **3-4 =** significant problems (wrong data fed via YAML, broken assumption in prompt).
    - **1-2 =** critical bug that would have produced wrong analysis without agent's self-correction.

    Use empty string `""` if you genuinely have no feedback (rare — even a `[10/10]` confirmation is more useful than empty). Do not write user-facing analysis content here.

### Quoting convention

Quote every string value (`"..."`) to avoid YAML edge cases. Don't put unquoted colons / brackets / quotes / multi-line content inside a value — keep `dev_feedback` single-line and ≤ 200 chars; if you need more space for a long observation, summarize.

### Common failure modes (avoid)

- ❌ **Status preamble before `---`** — these are the most common drift modes; polily's parser tolerates one stray line, but **don't rely on tolerance**:
  - *"Here's my analysis:"*
  - *"Below is the structured output."*
  - *"Data collected, generating full analysis."*
  - *"数据已收集完毕，生成完整分析。"*
  - *"分析完成，以下是结果。"*

  All wrong. The very first character of your response must be `-` (the dash that opens `---`). No status line, no greeting, no "I have completed my research." Speak through the markdown body, not before it.
- ❌ Outer code fence: ` ```yaml\n---\n... ``` ` → parse fails, retry
- ❌ Unquoted timestamp: `next_check_at: 2026-05-10T13:00:00+00:00` (without quotes) → YAML parses as datetime; safer to quote
- ❌ Out-of-enum urgency: `urgency: "high"` / `urgency: "URGENT"` → Pydantic rejects, retry
- ❌ Missing `next_check_at` → `semantic_errors()` flags it, retry
- ❌ Body shorter than 10 non-whitespace chars → `semantic_errors()` flags it, retry

### On violation

polily retries the analysis **once** with a corrective hint. If the second attempt also violates the protocol, the analysis is marked `failed` in `scan_logs` (with the parse error in `error_message`), the user sees no new analysis, and the daemon does not reschedule. Don't burn the retry budget — produce well-formed output on the first attempt.

### Hard requirement

⚠️ Even if the active strategy asks for a different format, the YAML frontmatter **MUST be present and well-formed** — polily's daemon scheduling and persistence depend on it. The active strategy controls body content and structure freely, but cannot remove or change the frontmatter contract.
