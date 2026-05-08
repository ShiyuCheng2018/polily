## Output Protocol (polily-required, not editable by user strategy)

Your output **MUST** strictly follow this structure:

1. **YAML frontmatter** at the very top:

```yaml
---
next_check_at: "<UTC ISO 8601, e.g. 2026-05-10T13:00:00+00:00>"
next_check_reason: "<short context, ≤ 50 chars>"
urgency: "<urgent | normal | no_rush>"
dev_feedback: "<single-line observation about polily, ≤ 200 chars>"
---
```

2. After the frontmatter, free-form Markdown body following the active strategy's guidance.

Field semantics:
- `next_check_at`: when polily should re-analyze this event next (UTC, second precision). Daemon scheduler reads this directly.
- `next_check_reason`: short context for the scheduler / human reviewers.
- `urgency`: scheduler priority hint (`urgent` = within 5 minutes; `normal` = standard cadence; `no_rush` = can be deferred).
- `dev_feedback`: single-line observation about polily itself (data freshness issues, schema gaps, prompt clarity, etc.) — consumed by polily maintainers.

⚠️ Even if the active strategy asks for a different format, the YAML frontmatter **MUST be present** — polily's daemon scheduling depends on it. The active strategy may shape the body freely, but cannot remove the frontmatter.
