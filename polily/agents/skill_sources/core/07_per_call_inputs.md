## 7. Per-Call Inputs

For each analysis, polily injects this YAML block at the very top of your prompt:

    language_directive: "<follow this output language strictly>"
    event_id: "<polymarket slug>"
    trigger: "<scan | movement | manual | scheduled>"
    timestamp_utc: "<UTC ISO 8601>"
    timestamp_local: "<local ISO 8601 with TZ>"
    has_position: <true | false>
    official_strategy_path: "<absolute path to packaged default.md>"

Treat every field above as source-of-truth for this analysis run. They override anything in the active strategy that contradicts.
