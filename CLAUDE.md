# CLAUDE.md

Instructions for Claude Code when working on this codebase.

## Product Identity

**Polily — Polymarket Decision Copilot**

Finds structure, surfaces risk, sizes friction, watches positions. The user pulls the trigger today. Autopilot is on the roadmap but not the current default — design new features so they remain compatible with both modes.

## User Profile

- Small account ($50–500), crypto + macro + tech expertise
- Picks events themselves; uses Polily for due diligence + monitoring (not market discovery)
- Reviews daily, 5–10 minutes
- Edge: crypto vol overpricing and crypto × macro cross-domain markets

## Red Lines

- Never output unconditional trade signals ("buy YES at any price")
- **Today** the loop stays human-in-the-loop. If we ship autopilot later, it must be opt-in, gated, and reversible — not silently enabled.
- Never promise profitability
- Never hide friction costs
- Never use `anthropic` SDK — all AI goes through `claude -p` CLI
- Never write "Never X" in public materials (README, release notes) — product direction may evolve

## Architecture (v0.5.0 — Event-First)

**Data model:** Events (parent) → Markets (children). All state in unified SQLite (`data/polily.db`). No scan archives, no JSON files. Events carry tier/score/monitor state; markets carry prices/orderbook.

**Entry flow:** **URL-driven, single-event.** User pastes a Polymarket event URL into the TUI. `scanner.url_parser` extracts the event slug. `scanner.scan.pipeline.fetch_and_score_event` fetches the event + child markets from Gamma API → applies hard filters → computes structure score (5-dim) → runs mispricing detection → optionally calls NarrativeWriter agent → assigns tier → persists to events/markets tables. **There is no batch scan over 8000+ markets** — that pattern was removed in v0.5.0.

**Poll architecture:** Single global poll job runs every **30 seconds** on a dedicated 1-thread executor. Fetches prices for all markets the user has added to monitoring. Movement detection runs inline per tick (magnitude + quality scoring). If significant movement detected, triggers AI analysis on the `ai` executor (5 threads).

**Daemon:** Dual-executor APScheduler daemon (`scanner/daemon/scheduler.py`). Poll executor (1 thread) for price polling. AI executor (5 threads) for concurrent analysis jobs. Managed via `polily scheduler run/stop/restart/status`. Started via launchd in production.

**Why Decision Copilot, not Research Assistant?**
Users don't want data dumps. They want help making decisions. Conditional advice ("if you're bullish, this may have edge") is OK. Definitive signals are not.

**Why Structure Score ≠ trade quality?**
Score measures tradability (spread, depth, objectivity, time, friction). Not profitability. Always communicate it that way to users.

**Why URL-driven instead of batch scanning?**
Users have domain edge in specific events — they already know what they want to look at. Batch scanning produced noise and rate-limit issues; deep single-event analysis is what actually informs decisions.

**Why Binance (ccxt) not CoinGecko?**
CoinGecko free tier rate-limits aggressively (429 errors). Binance via ccxt has 6000 weight/min, no API key needed, first-party exchange data.

**Why AI agents use `claude -p` CLI?**
Included in Claude subscription, no per-token cost. Response parsed from `result` field (not `structured_output`). JSON extracted from markdown code blocks via regex fallback.

## Coding Conventions

- Python 3.11+, type hints everywhere
- Pydantic for data models and config
- `async` for I/O (HTTP, ccxt), `sync` for pipeline orchestration
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
| `scanner/cli.py` | CLI: TUI launch + `scheduler` subcommands + `reset` |
| `scanner/url_parser.py` | Polymarket URL → event slug |
| `scanner/scan_log.py` | Scan log entries (per-event run history) |
| `scanner/analysis_store.py` | NarrativeWriter analysis versions per event |
| `scanner/core/db.py` | Unified SQLite database (PolilyDB) |
| `scanner/core/config.py` | All Pydantic config models |
| `scanner/core/models.py` | Market, BookLevel, Trade models |
| `scanner/core/event_store.py` | EventRow, MarketRow, upsert/query |
| `scanner/core/paper_store.py` | Paper trade CRUD + P&L |
| `scanner/core/monitor_store.py` | Event monitor state (auto_monitor, next_check_at) |
| `scanner/scan/pipeline.py` | **Single-event** orchestrator: fetch → filter → score → mispricing → AI → tier |
| `scanner/scan/scoring.py` | Structure score (5-dimension) |
| `scanner/scan/event_scoring.py` | Event-level aggregation + tier assignment |
| `scanner/scan/filters.py` | Hard filters |
| `scanner/scan/mispricing.py` | Crypto vol-implied mispricing detection |
| `scanner/scan/commentary.py` | Per-dimension score commentary |
| `scanner/scan/tag_classifier.py` | Market type / tag classification |
| `scanner/monitor/scorer.py` | Movement scorer (magnitude + quality) |
| `scanner/monitor/signals.py` | Movement signal computation |
| `scanner/monitor/drift.py` | CUSUM drift detector |
| `scanner/monitor/store.py` | Movement records storage |
| `scanner/monitor/event_metrics.py` | Per-event movement metrics |
| `scanner/daemon/scheduler.py` | APScheduler daemon: dual executor + launchd |
| `scanner/daemon/poll_job.py` | Global poll job (30s) — fetch prices for monitored markets |
| `scanner/daemon/recheck.py` | Scheduled event recheck (AI analysis) |
| `scanner/daemon/auto_monitor.py` | Auto-monitor toggle logic |
| `scanner/daemon/score_refresh.py` | Periodic structure-score refresh |
| `scanner/daemon/notify.py` | Notification dispatch |
| `scanner/agents/base.py` | BaseAgent: claude CLI invoke + retry + JSON parsing |
| `scanner/agents/narrative_writer.py` | NarrativeWriter agent (decision advisor) |
| `scanner/agents/schemas.py` | Pydantic schemas for agent I/O |
| `scanner/agents/prompts/` | Markdown prompt files for agents |
| `scanner/tui/app.py` | Textual TUI entry point |
| `scanner/tui/screens/main.py` | Main screen: sidebar + content + worker |
| `scanner/tui/service.py` | `ScanService` — bridge between TUI views and backend |
| `scanner/tui/views/` | Per-pane views (scan_log, monitor_list, paper_status, market_detail, notification_list, history) |

## Common Pitfalls

- **No batch scan.** If a feature seems to require iterating all 8000 markets, it's likely a misunderstanding — the pipeline is single-event by URL. Batch poll only covers markets the user has explicitly added to monitoring.
- NarrativeWriter agent uses `claude -p --allowedTools Read,Bash,Grep,WebSearch,StructuredOutput` — agent autonomously reads DB, searches web, then outputs via StructuredOutput. Prompt rules in `scanner/agents/prompts/narrative_writer.md`.
- `claude -p --output-format json` (CLI v2.1+) returns a **JSON array**: `[{"type":"system",...}, {"type":"assistant",...}, {"type":"result","result":"..."}]`. Find the `{"type":"result"}` element (last in array), then parse `result` field.
- TUI exit uses `os._exit(0)` because `claude -p` spawns Node.js subprocesses that survive normal shutdown.
- Textual workers: pass function reference (no parentheses), not coroutine. All UI updates from worker threads must use `call_from_thread`.
- Global poll runs every **30s** on a dedicated single-thread executor. Movement detection is inline (no separate job). AI analysis is triggered on the ai executor (5 threads).
- Daemon writes PID to `data/scheduler.pid`. CLI `stop` reads PID and sends SIGTERM. `SIGUSR1` triggers job reload from DB.
- **CLOB /book API returns distorted books for negRisk markets** (GitHub Issue #180): returns the raw token book with bid=0.01 / ask=0.99, which does not reflect the real liquidity provided by complement matching. Use `/midpoint` for the true price and the difference between `/price?side=BUY` and `/price?side=SELL` for the true spread. `/book` depth data is unreliable for negRisk markets.

## Release Process

Polily is open source; releases need to follow a standard. Always use `gh release create` (which creates the tag and release page together); don't run `git tag` standalone.

| Stage | Branch | Command | GitHub label |
|-------|--------|---------|--------------|
| Early access | dev | `gh release create v0.6.0-beta.1 --target dev --prerelease` | Pre-release |
| Stable | master | `gh release create v0.6.0 --target master` | Latest |

**Cadence:**
1. Feature-complete on dev → ship `vX.Y.0-beta.N` (prerelease)
2. Collect feedback, fix bugs → ship `vX.Y.0-beta.N+1` (prerelease)
3. Once stable, merge to master → ship `vX.Y.0` (latest)
