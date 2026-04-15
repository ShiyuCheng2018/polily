# CLAUDE.md

Instructions for Claude Code when working on this codebase.

## Product Identity

**Polily — Polymarket Decision Copilot**

Finds structure, shows direction lean, sizes risk. User pulls the trigger. Not a signal generator, not an auto-trader.

## User Profile

- $50-200 small account, crypto + macro + tech expertise
- Scans daily, 5-10 minutes
- Edge: crypto x macro cross-domain markets
- Wants help deciding, not just data

## Red Lines (Never Do)

- Never output definitive trade signals ("buy YES")
- Never auto-execute trades
- Never promise profitability
- Never hide friction costs
- Never use `anthropic` SDK — all AI goes through `claude -p` CLI
- Never break the human-in-the-loop model

## Architecture (v0.5.0 — Event-First)

**Data model:** Events (parent) -> Markets (children). All state in unified SQLite (`data/polily.db`). No scan archives, no JSON files. Events carry tier/score, markets carry prices/orderbook.

**Poll architecture:** Single global poll job (10s interval, 1 thread) fetches prices for all monitored markets. Movement detection runs inline per tick. If significant movement detected, triggers AI analysis on the `ai` executor (5 threads).

**Daemon:** Dual-executor APScheduler daemon (`scanner/daemon/scheduler.py`). Poll executor (1 thread) for price polling. AI executor (5 threads) for concurrent analysis jobs. Managed via `polily scheduler run/stop/restart/status`.

**Scan pipeline:** Fetches markets from Gamma API -> hard filters -> structure scoring -> mispricing detection -> AI narrative -> tier assignment. Results persisted to events/markets tables.

**Why Decision Copilot, not Research Assistant?**
Users don't want data dumps. They want help making decisions. Conditional advice ("if you're bullish, this may have edge") is OK. Definitive signals are not.

**Why Structure Score != trade quality?**
Score measures tradability (spread, depth, objectivity, time). Not profitability. Must always be communicated this way.

**Why `--lean` is off by default?**
Direction advice can anchor users. Off by default protects conservative users. Power users opt in via `--lean` or config.

**Why Binance (ccxt) not CoinGecko?**
CoinGecko free tier rate-limits aggressively (429 errors). Binance via ccxt has 6000 weight/min, no API key needed, first-party exchange data.

**Why AI agents use `claude -p` CLI?**
Included in Claude subscription, no per-token cost. Response parsed from `result` field (not `structured_output`). JSON extracted from markdown code blocks via regex fallback.

## Coding Conventions

- Python 3.11+, type hints everywhere
- Pydantic for data models and config
- `async` for API calls, `sync` for pipeline orchestration
- TDD: write test first (red), implement (green), refactor
- Chinese for all user-facing output (terminal, narratives, prompts)
- English for code, variable names, comments
- No unnecessary abstractions — three similar lines beats a premature abstraction
- Config-driven: thresholds, weights, behavior all in YAML
- Single AI agent (NarrativeWriter) with rule-based fallback

## Key Files

| File | Role |
|------|------|
| `scanner/__init__.py` | Public API surface (v0.5.0) |
| `scanner/core/db.py` | Unified SQLite database (PolilyDB) |
| `scanner/core/config.py` | All Pydantic config models |
| `scanner/core/models.py` | Market, BookLevel, Trade models |
| `scanner/core/event_store.py` | EventRow, MarketRow, upsert/query functions |
| `scanner/core/paper_store.py` | Paper trade CRUD + P&L |
| `scanner/core/monitor_store.py` | Event monitor state (auto_monitor, next_check_at) |
| `scanner/scan/pipeline.py` | Orchestrator: filter -> score -> mispricing -> AI -> tier |
| `scanner/scan/scoring.py` | Structure score (5-dimension) |
| `scanner/scan/filters.py` | Hard filters |
| `scanner/scan/mispricing.py` | Crypto vol-implied mispricing detection |
| `scanner/monitor/poll.py` | Global poll: fetch prices for all monitored markets |
| `scanner/monitor/scorer.py` | Movement scorer (magnitude + quality) |
| `scanner/monitor/signals.py` | Movement signal computation |
| `scanner/monitor/drift.py` | CUSUM drift detector |
| `scanner/daemon/scheduler.py` | APScheduler daemon: dual executor + launchd |
| `scanner/daemon/poll_job.py` | Poll job entry point (called by scheduler) |
| `scanner/daemon/recheck.py` | Scheduled event recheck (AI analysis) |
| `scanner/daemon/auto_monitor.py` | Auto-monitor toggle logic |
| `scanner/agents/base.py` | BaseAgent: claude CLI invoke + retry + JSON parsing |
| `scanner/agents/narrative_writer.py` | NarrativeWriter agent (decision advisor) |
| `scanner/tui/app.py` | Textual TUI entry point |
| `scanner/tui/screens/main.py` | Main screen: sidebar + content + worker |
| `scanner/cli.py` | CLI: TUI launch + scheduler commands |

## Common Pitfalls

- NarrativeWriter agent uses `claude -p --allowedTools Read,Bash,Grep,WebSearch,StructuredOutput` — agent autonomously reads DB, searches web, then outputs via StructuredOutput. Prompt rules in `scanner/agents/prompts/narrative_writer.md`.
- `claude -p --output-format json` (CLI v2.1+) returns a **JSON array**: `[{"type":"system",...}, {"type":"assistant",...}, {"type":"result","result":"..."}]`. Find the `{"type":"result"}` element (last in array), then parse `result` field. Legacy mode uses `--bare`, tool mode does not.
- TUI exit uses `os._exit(0)` because `claude -p` spawns Node.js subprocesses that survive normal shutdown.
- `run_worker(self._do_scan, thread=True)` — pass function reference (no parentheses), not coroutine. All UI updates from worker must use `call_from_thread`.
- Global poll runs every 30s on a dedicated single-thread executor. Movement detection is inline (no separate job). AI analysis is triggered on the ai executor (5 threads).
- Daemon writes PID to `data/scheduler.pid`. CLI `stop` reads PID and sends SIGTERM. `SIGUSR1` triggers job reload from DB.
- **CLOB /book API 对 negRisk 市场盘口失真**（GitHub Issue #180）：返回原始 token 盘口 bid=0.01 ask=0.99，不反映 complement matching 的真实流动性。真实价格用 `/midpoint`，真实 spread 用 `/price?side=BUY` 和 `/price?side=SELL` 的差值。`/book` 的 depth 数据对 negRisk 市场不可靠。
