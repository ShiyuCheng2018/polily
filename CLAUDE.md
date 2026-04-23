# CLAUDE.md

Instructions for Claude Code when working on this codebase.

## Product Identity

**Polily — A Polymarket Monitoring Agent That Actually Works**

Finds structure, surfaces risk, sizes friction, watches positions. The user pulls the trigger today. Autopilot is on the roadmap but not the current default — design new features so they remain compatible with both modes.

## Design Context

Not a user-profile spec — these are facts about how the product is used, useful when deciding trade-offs:

- **Small-account usage pattern.** $5 in friction cost is not a rounding error at this tier. Surface every fee / slippage component explicitly; never silently absorb costs into a "net" number.
- **Manual operation, not automation.** Users click buttons; sub-second latency isn't the pressure. But signals must be scannable — a user should decide "look closer vs. skip" in ≤5s.
- **Daily review cadence.** ≥5s refresh intervals are fine; no tick-level streaming UI needed. Heartbeat-driven refresh (see `polily/tui/screens/main.py::_bus_heartbeat`) is the canonical pattern.
- **URL-driven depth, not scan breadth.** Users bring their own events. The pipeline is deep due-diligence on one event at a time, not shallow breadth across thousands. If a feature requires iterating 8000+ markets, it's likely a misunderstanding of the product shape.
- **Due diligence, not signal generation.** Output is "here's what the numbers say, here's the risk, here's the friction" — conditional framing, never unconditional commands like "buy YES".

## Architecture (Event-First)

**Data model:** Events (parent) → Markets (children). All state in unified SQLite (`data/polily.db`). No scan archives, no JSON files. Events carry tier/score/monitor state; markets carry prices/orderbook.

**Entry flow:** **URL-driven, single-event.** User pastes a Polymarket event URL into the TUI. `polily.url_parser` extracts the event slug. `polily.scan.pipeline.fetch_and_score_event` fetches the event + child markets from Gamma API → applies hard filters → computes structure score (5-dim) → runs mispricing detection → optionally calls NarrativeWriter agent → assigns tier → persists to events/markets tables. **There is no batch scan over 8000+ markets** — that pattern was removed in v0.5.0.

**Poll architecture:** Single global poll job runs every **30 seconds** on a dedicated 1-thread executor. Fetches prices for all markets the user has added to monitoring. Movement detection runs inline per tick (magnitude + quality scoring). If significant movement detected, triggers AI analysis on the `ai` executor (5 threads).

**Daemon:** Dual-executor APScheduler daemon (`polily/daemon/scheduler.py`). Poll executor (1 thread) for price polling. AI executor (5 threads) for concurrent analysis jobs. Managed via `polily scheduler run/stop/restart/status`. Started via launchd in production.

**Why "monitoring agent" rather than research assistant / signal generator?**
Users don't want data dumps (research) or commands (signals). They want something that keeps watching on their behalf and surfaces what actually changed — price moves, structure shifts, position risk, end-dates coming up. Conditional advice ("if you're bullish, this may have edge") is OK. Definitive signals are not.

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
- Single AI agent (NarrativeWriter). No silent fallback — CLI failures raise and land as `failed` scan_logs rows.
- **All AI calls go through `claude -p` CLI**, never the `anthropic` SDK. Reason: uses the user's Claude Code subscription instead of per-token billing. `BaseAgent` at `polily/agents/base.py` is the only place that shells out — don't add a second integration path.

## Key Files

| File | Role |
|------|------|
| `polily/__init__.py` | Public API surface (v0.6.0) |
| `polily/cli.py` | CLI: TUI launch + `scheduler` subcommands + `reset` (`--wallet-only`) |
| `polily/url_parser.py` | Polymarket URL → event slug |
| `polily/scan_log.py` | Scan log entries (per-event run history) |
| `polily/analysis_store.py` | NarrativeWriter analysis versions per event |
| `polily/core/db.py` | Unified SQLite database (PolilyDB) |
| `polily/core/config.py` | All Pydantic config models |
| `polily/core/models.py` | Market, BookLevel, Trade models |
| `polily/core/event_store.py` | EventRow, MarketRow, upsert/query |
| `polily/core/lifecycle.py` | Market / Event lifecycle state derivation (v0.8.5). `MarketState` (TRADING / PENDING_SETTLEMENT / SETTLING / SETTLED) + `EventState` (ACTIVE / AWAITING_FULL_SETTLEMENT / RESOLVED) derived from `closed` + `end_date` + `resolved_outcome` — no DB column, derive-on-read |
| `polily/core/monitor_store.py` | Event monitor state (v0.7.0: user-intent flag only — `auto_monitor` / `price_snapshot` / `notes`) |
| `polily/core/wallet.py` | WalletService — cash + ledger + atomicity contract (commit=False) |
| `polily/core/positions.py` | PositionManager — aggregated (market_id, side) positions, weighted-avg cost |
| `polily/core/trade_engine.py` | TradeEngine — atomic buy/sell (wallet + position + fee in one BEGIN/COMMIT) |
| `polily/core/fees.py` | Polymarket category-based taker fee curve |
| `polily/core/wallet_reset.py` | Hard reset util (requires no concurrent writer — see docstring) |
| `polily/scan/pipeline.py` | **Single-event** orchestrator: fetch → filter → score → mispricing → AI → tier |
| `polily/scan/scoring.py` | Structure score (5-dimension) |
| `polily/scan/event_scoring.py` | Event-level aggregation + tier assignment |
| `polily/scan/filters.py` | Hard filters |
| `polily/scan/mispricing.py` | Crypto vol-implied mispricing detection |
| `polily/scan/commentary.py` | Per-dimension score commentary |
| `polily/scan/tag_classifier.py` | Market type / tag classification |
| `polily/monitor/scorer.py` | Movement scorer (magnitude + quality) |
| `polily/monitor/signals.py` | Movement signal computation |
| `polily/monitor/drift.py` | CUSUM drift detector |
| `polily/monitor/store.py` | Movement records storage |
| `polily/monitor/event_metrics.py` | Per-event movement metrics |
| `polily/daemon/scheduler.py` | APScheduler daemon: dual executor + launchd; wires scheduler into `_ctx` so `global_poll`'s Step 3.5 dispatcher can submit. Plist auto-heal in `ensure_daemon_running` (v0.9.0) |
| `polily/daemon/launchctl_query.py` | `launchctl list com.polily.scheduler` parser + `kill_daemon(sig)` helper (v0.9.0). Replaced `data/scheduler.pid` as source of truth for "is daemon alive" |
| `polily/daemon/poll_job.py` | Global poll job (30s): fetch prices → auto-resolution → score refresh → **Step 3.5 dispatcher (drain overdue `scan_logs` pending rows)** → intelligence layer |
| `polily/daemon/resolution.py` | ResolutionHandler — atomic per-market settle on Gamma outcomePrices |
| `polily/daemon/close_event.py` | Event archival / close handling |
| `polily/daemon/auto_monitor.py` | Auto-monitor toggle logic |
| `polily/daemon/score_refresh.py` | Periodic structure-score refresh |
| `polily/agents/narrator_registry.py` | In-process narrator cancel registry (scope: process-local; see docstring for cross-process limitation) |
| `polily/agents/base.py` | BaseAgent: claude CLI invoke + retry + JSON parsing |
| `polily/agents/narrative_writer.py` | NarrativeWriter agent (decision advisor) |
| `polily/agents/schemas.py` | Pydantic schemas for agent I/O |
| `polily/agents/prompts/` | Markdown prompt files for agents |
| `polily/tui/app.py` | Textual TUI entry point |
| `polily/tui/screens/main.py` | Main screen: sidebar + content + worker (menu: tasks/monitor/paper/wallet/history/notifications); 5s `_bus_heartbeat` bridges daemon-side DB writes to TUI subscribers |
| `polily/tui/_dispatch.py` | `dispatch_to_ui(app, fn)` thread-hop helper + `@once_per_tick` coalescing decorator (React-style batching). Load-bearing for heartbeat-driven refresh — see v0.9.0 `call_later` signature fix |
| `polily/tui/service.py` | `PolilyService` — bridge between TUI views and backend; owns wallet/positions/trade_engine |
| `polily/tui/views/` | Per-pane views (scan_log, monitor_list, paper_status, event_detail, wallet, history, archived_events, changelog) |
| `polily/tui/views/changelog.py` | ChangelogView — renders CHANGELOG.md via Markdown widget; reads from repo root in dev or from packaged resource (see `pyproject.toml` `force-include`) in installed wheels |
| `polily/tui/views/trade_dialog.py` | Modal with Buy/Sell tabs — calls TradeEngine.execute_buy/sell |
| `polily/tui/views/wallet.py` | WalletView — balance + transactions ledger + topup/withdraw/reset |
| `polily/tui/views/wallet_modals.py` | TopupModal / WithdrawModal / WalletResetModal |

## Common Pitfalls

- **No batch scan.** If a feature seems to require iterating all 8000 markets, it's likely a misunderstanding — the pipeline is single-event by URL. Batch poll only covers markets the user has explicitly added to monitoring.
- NarrativeWriter agent uses `claude -p --allowedTools Read,Bash,Grep,WebSearch,StructuredOutput` — agent autonomously reads DB, searches web, then outputs via StructuredOutput. Prompt rules in `polily/agents/prompts/narrative_writer.md`.
- `claude -p --output-format json` (CLI v2.1+) returns a **JSON array**: `[{"type":"system",...}, {"type":"assistant",...}, {"type":"result","result":"..."}]`. Find the `{"type":"result"}` element (last in array), then parse `result` field.
- TUI exit uses `os._exit(0)` because `claude -p` spawns Node.js subprocesses that survive normal shutdown.
- Textual workers: pass function reference (no parentheses), not coroutine. All UI updates from worker threads must use `call_from_thread`.
- Global poll runs every **30s** on a dedicated single-thread executor. Movement detection is inline (no separate job). AI analysis is triggered on the ai executor (5 threads).
- Daemon aliveness + PID lookup all go through `launchctl list com.polily.scheduler` (see `polily/daemon/launchctl_query.py`). The legacy `data/scheduler.pid` file was dropped in v0.9.0 — launchctl is the single source of truth. `SIGUSR1` still triggers job reload from DB.
- **CLOB /book API returns distorted books for negRisk markets** (GitHub Issue #180): returns the raw token book with bid=0.01 / ask=0.99, which does not reflect the real liquidity provided by complement matching. Use `/midpoint` for the true price and the difference between `/price?side=BUY` and `/price?side=SELL` for the true spread. `/book` depth data is unreliable for negRisk markets.
- **`paper_trades` no longer exists.** Dropped in v0.6.1 — `positions` + `wallet_transactions` are the only trade-state tables. On DB init, `PolilyDB._init_schema` executes `DROP TABLE IF EXISTS paper_trades` so old installs auto-clean. All writes go through `TradeEngine.execute_buy/sell`; history reads go through `PolilyService.get_realized_history` (SELL + RESOLVE ledger rows).
- **`wallet.credit(commit=False)` defers the cash write to the outer transaction.** `ResolutionHandler.resolve_market` wraps one BEGIN around the credit + position delete + ledger insert, so passing `commit=True` would split them and re-credit on retry. Any new "bulk close" code path must preserve this contract (see `polily/core/wallet.py:113-154`).
- **`reset_wallet` has no built-in writer lock.** The CLI path stops the scheduler daemon first; the TUI `WalletResetModal` sends SIGTERM + 1s grace before calling reset (on a worker thread so the event loop doesn't freeze). Any new caller MUST guarantee no concurrent writer — otherwise DELETE races with a mid-flight poll INSERT.
- **`cumulative_realized_pnl` on the wallet snapshot is derived**, not stored: `SUM(wallet_transactions.realized_pnl) WHERE realized_pnl IS NOT NULL`. Goes to 0 automatically after reset (wallet_transactions is cleared). Don't try to mirror it into a stored column.

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

**CHANGELOG.md workflow** (Keep a Changelog + SemVer):
- Update `[Unreleased]` as part of every PR that has user-visible change. Don't let it drift — it's the source of truth for what ships next.
- Before `gh release create`, diff dev since the last tag and cross-check that every commit with user-visible impact is already in `[Unreleased]` (or the version section). Commits made after the PR merged (hotfixes, follow-ups, docs-only cleanups) are the usual gap.
- On release, rename `[Unreleased]` → `[X.Y.Z] — YYYY-MM-DD` and update the compare/tag links at the bottom. Don't open a new section for the same version across beta→stable — keep accumulating in one section so the stable release notes reflect the cumulative truth.
- If you realize post-release the section missed something, patch that version's section directly (commit to dev titled `docs(changelog): catch up [X.Y.Z]`), don't start a new section.

**Branch channel discipline:**
- **dev is the only channel to master.** Every PR into master MUST have `head=dev`. Never open a PR to master from a release branch, feature branch, or any other source — even if the content would be identical to dev.

**Merge strategy per PR type:**
- **Feature PR → dev**: squash merge (keep dev's log granular, one commit per feature).
- **Release PR `dev → master`**: **"Create a merge commit"** — NOT squash. The merge commit preserves dev's commits as ancestors of master, so the next release PR is a clean fast-forward.
- **Sync PR (one-time fix when ancestry is broken)**: merge commit. Same reason.
- **Why this matters:** v0.6.0 + v0.6.1 both had 5-file conflicts on `dev → master` because prior syncs/releases were squashed — that collapses master's history into a single commit on dev (or vice versa), losing the ancestry link. v0.6.1's PR #43 + #44 both used merge commits to establish proper ancestry; v0.6.2 and forward should be clean fast-forwards.
- **Repo setting**: `allow_merge_commit=true` (enabled 2026-04-19 as part of v0.6.1 release). `allow_squash_merge=true` stays on for feature PRs.

**Auto-sync master → dev (post-v0.9.0)**:
- `.github/workflows/sync-master-to-dev.yml` triggers on every push to master (including release merge-commits).
- Workflow opens `sync/master-into-dev-<timestamp>` PR and enables auto-merge; once CI passes, GitHub merges it with a merge-commit, restoring dev as a strict descendant of master.
- Net effect: after a release PR merges, the next release PR is a clean fast-forward within a few minutes. **No manual sync work needed.**
- If the auto-sync ever fails (CI red on the sync PR, merge conflict, workflow disabled), fall back to the manual steps below.

**Manual sync fallback** (only if auto-sync fails):
1. Branch `sync/master-into-dev` from dev.
2. `git merge origin/master`, resolve conflicts (usually take dev's version — it's the newer state).
3. PR that branch → **dev** (not master). **Merge via "Create a merge commit"**, not squash.
4. After merge, dev is a clean descendant of master. Open the release PR dev → master (clean fast-forward).
