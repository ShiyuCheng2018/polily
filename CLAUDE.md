# CLAUDE.md

Instructions for Claude Code when working on this codebase.

## Product Identity

**Polily — Polymarket Decision Copilot**

Finds structure, shows direction lean, sizes risk. User pulls the trigger. Not a signal generator, not an auto-trader.

## User Profile

- $50-200 small account, crypto + macro + tech expertise
- Scans daily, 5-10 minutes
- Edge: crypto × macro cross-domain markets
- Wants help deciding, not just data

## Red Lines (Never Do)

- Never output definitive trade signals ("buy YES")
- Never auto-execute trades
- Never promise profitability
- Never hide friction costs
- Never use `anthropic` SDK — all AI goes through `claude -p` CLI
- Never break the human-in-the-loop model

## Architecture Decisions (Why, Not How)

**Why Decision Copilot, not Research Assistant?**
Users don't want data dumps. They want help making decisions. Conditional advice ("if you're bullish, this may have edge") is OK. Definitive signals are not.

**Why Structure Score ≠ trade quality?**
Score measures tradability (spread, depth, objectivity, time). Not profitability. Must always be communicated this way.

**Why `--lean` is off by default?**
Direction advice can anchor users. Off by default protects conservative users. Power users opt in via `--lean` or config.

**Why Binance (ccxt) not CoinGecko?**
CoinGecko free tier rate-limits aggressively (429 errors). Binance via ccxt has 6000 weight/min, no API key needed, first-party exchange data.

**Why AI agents use `claude -p` CLI?**
Included in Claude subscription, no per-token cost. Response parsed from `result` field (not `structured_output`). JSON extracted from markdown code blocks via regex fallback.

**Why paper_trades uses SQLite but scans use JSON?**
Paper trades need CRUD + aggregation → SQLite. Scan archives are append-only immutable snapshots → JSON files (jq-friendly, no migration needed).

**Why unified archive (no separate outputs/ and data/scans/)?**
Single source of truth. All tiers saved with `"tier": "research"|"watchlist"|"filtered"` label. Consumers filter by tier.

## Coding Conventions

- Python 3.11+, type hints everywhere
- Pydantic for data models and config
- `async` for API calls, `sync` for pipeline orchestration
- TDD: write test first (red), implement (green), refactor
- Chinese for all user-facing output (terminal, narratives, prompts)
- English for code, variable names, comments
- No unnecessary abstractions — three similar lines beats a premature abstraction
- Config-driven: thresholds, weights, behavior all in YAML
- Every AI agent has a rule-based fallback

## Key Files

| File | Role |
|------|------|
| `scanner/__init__.py` | Public API surface |
| `scanner/pipeline.py` | Orchestrator: filter → score → mispricing → AI → tier |
| `scanner/config.py` | All Pydantic config models |
| `scanner/agents/base.py` | BaseAgent: claude CLI invoke + retry + JSON parsing |
| `scanner/tui/app.py` | Textual TUI entry point |
| `scanner/tui/screens/main.py` | Main screen: sidebar + content + worker |

## Common Pitfalls

- `claude -p --output-format json` (CLI v2.1+) returns a **JSON array**: `[{"type":"system",...}, {"type":"assistant",...}, {"type":"result","result":"..."}]`. Find the `{"type":"result"}` element (last in array), then parse `result` field. Uses `--bare` to skip hooks/plugins overhead. Legacy single-object format `{"type":"result","result":"..."}` is also handled.
- Pipeline's `_timed_status` uses threading for spinner — don't mix with direct UI updates in Textual TUI mode. Set `POLILY_TUI=1` env var to silence Rich console.
- `run_worker(self._do_scan, thread=True)` — pass function reference (no parentheses), not coroutine. All UI updates from worker must use `call_from_thread`.
- TUI exit uses `os._exit(0)` because `claude -p` spawns Node.js subprocesses that survive normal shutdown. This is a known limitation documented in README.
