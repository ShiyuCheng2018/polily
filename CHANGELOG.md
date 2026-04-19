# Changelog

All notable changes to Polily are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelog started at v0.6.0; prior versions (v0.5.x and earlier) have no
structured release notes — see `git log` for history.

## [Unreleased]

### Added

- **Binary event structure panel**: binary (single-market) events on the
  detail page now show the same 5-dimension score breakdown + per-dim
  commentary that multi-market events expose via row expansion. Flat
  layout (label / bar / score / comment) plus an overall summary line.
  `SubMarketTable` still owns multi-market rendering.

## [0.6.0] — 2026-04-19

Wallet system — paper trading gets real. Buys and sells now settle against
a single cash balance, positions aggregate across trades, and markets
auto-resolve when Polymarket publishes outcomes.

First shipped as `v0.6.0-beta.1` on 2026-04-19.

### Added

- **Wallet**: real cash balance with topup / withdraw, a `wallet_transactions`
  ledger, and a `cumulative_realized_pnl` metric derived from SELL + RESOLVE
  rows. Starts at $100, configurable via `wallet.starting_balance`.
- **Aggregated positions**: same `(market_id, side)` → one position with
  weighted-average `avg_cost`. YES and NO can coexist on the same market.
- **Full action set**: buy / add / reduce / close, all from the upgraded
  Trade Dialog (Buy tab + Sell tab). Execute paths are atomic —
  `TradeEngine` opens one BEGIN per operation covering wallet debit, fee
  debit, and position mutation, with rollback on any failure.
- **Polymarket-accurate taker fees**: driven by each market's own
  `feesEnabled` gate + `feeSchedule.rate` coefficient as returned by Gamma.
  Most markets (Politics / Sports majors / Geopolitics) have fees disabled;
  short-term crypto / sports markets use `crypto_fees_v2` / `sports_fees_v2`
  schedules (rate 0.072 / 0.03 around the 0.5 peak).
- **Auto resolution**: `poll_job` detects closed markets with positions,
  fetches `outcomePrices` from Gamma, and settles through
  `ResolutionHandler` in one transaction — cash credited, position row
  deleted, audit line logged.
- **UMA resolution gate**: `derive_winner` now honors Gamma's
  `umaResolutionStatuses` history array. Settlement only proceeds when the
  array is empty (non-UMA markets like crypto price-feeds) or the last
  entry is `"resolved"` (UMA final). During the 2+ hour challenge window
  (last entry `"proposed"` or `"disputed"`), we defer to the next poll
  tick — prevents phantom RESOLVE rows if a dispute flips the outcome.
- **Realized-P&L history**: `HistoryView` rewritten to source from
  `wallet_transactions` (SELL + RESOLVE rows), one row per realized event
  in reverse chronological order. Joined FEE rows surface the real
  per-sell friction instead of the legacy hardcoded 4% estimate.
- **Auto-restart daemon after wallet reset**: `WalletResetModal` now
  restarts the scheduler automatically once reset commits (skips restart
  when no active monitors exist). Users no longer need to run
  `polily scheduler restart` manually.
- **Per-restart versioned poll logs**: daemon writes to
  `data/logs/poll-v<version>-<YYYYMMDD-HHMMSS>.log`; every launch gets a
  fresh file and older logs are retained for diffing behavior across
  restarts.
- **TUI always restarts the daemon on launch** (when monitored events
  exist), so code changes since the last daemon start take effect without
  a separate restart command.
- **New TUI Wallet page** (menu `3`): balance panel (equity / cash /
  positions market value / realized / unrealized / ROI), recent
  transactions ledger, top-up / withdraw / reset actions.
- **`polily reset --wallet-only`**: CLI flag to wipe wallet-side tables
  without losing events, markets, or AI analyses.
- **`markets.resolved_outcome` column**: structured per-market winner
  (`yes` / `no` / `invalid` / NULL), populated during resolution.

### Changed

- **TUI menu renumber**: `钱包` inserted at slot `3`; `历史` shifted to `4`,
  `通知` to `5`.
- **`paper_trades` table dropped**. Reads moved to `positions` +
  `wallet_transactions` across all call sites (HistoryView,
  MarketDetailView, ScanService event detail / AI context builder). On
  upgraded databases, `PolilyDB._init_schema` runs `DROP TABLE IF EXISTS
  paper_trades` — idempotent, no-op on fresh installs.
- **`narrative_writer.md` prompt**: now reads `wallet`, `positions`,
  `wallet_transactions` (was `paper_trades`). Adds "全方位管理" guidance
  so the agent can give position-sizing and correlation-risk advice
  based on the full wallet context.
- **Fee arithmetic keyed on the market row**: `calculate_taker_fee` now
  takes `fees_enabled` + `fee_rate` kwargs (was category-based guess).
  Source of truth is each market's own Gamma response.
- **Best-side spread across the scoring stack**: friction, liquidity
  quality, value score, and the filter threshold all compute
  `spread_abs / max(mid_yes, mid_no)` instead of `spread_abs / mid_yes`.
  Reflects the cheaper trading direction on low-yes markets; previously
  inflated friction 2-5x on events with YES below 30¢.

### Fixed

- **MarketDetailView showed "无持仓" for live positions**: the event
  detail page's position panel read the legacy `paper_trades` table,
  which v0.6.0 TradeEngine had stopped writing to. Now sources from
  `positions` via `get_event_detail`.
- **`analyze_event` lost position context**: `has_position` check also
  read legacy `paper_trades`, leaving the AI narrative agent in
  `discovery` mode even when the user had live positions. Rewired to
  read `positions`, and the agent now correctly enters
  `position_management` mode with thesis tracking and stop/target
  operators.
- **Pre-existing agent bug**: `narrative_writer.md` had been SELECTing
  three non-existent columns from `paper_trades` (`exit_price`,
  `realized_pnl`, `created_at`). Agent silently swallowed the
  OperationalError and proceeded without trade history; fix migrates to
  the new schema and the history flows through correctly.

### Removed

- `scanner/core/paper_store.py` — every caller migrated to
  `positions` / `wallet_transactions`.
- `scanner/core/migration_v060.py` — one-shot migration shim is no longer
  needed now that the source table is dropped.
- `scanner/export.py` — orphan module with no callers.
- `ScanService.create_paper_trade` / `get_resolved_trades` /
  `get_trade_stats` — legacy bridges to `paper_store`.

### Breaking Changes (v0.5.x → v0.6.0)

Migration is automatic for end users — these affect only callers of
`scanner` as a library.

- `paper_trades` table no longer exists. `DROP TABLE IF EXISTS` runs on
  first launch of an upgraded DB; any external reader of the table must
  switch to `positions` / `wallet_transactions`.
- `ScanService.get_open_trades()` return shape changed. Rows are now
  keyed by the synthetic composite `{market_id}:{side}` and sourced from
  `positions` (one per aggregated position, not per trade). Shim
  preserves pre-existing keys (`id`, `entry_price`, `position_size_usd`,
  etc.) so the TUI view is untouched, but legacy columns like
  `exit_price`, `realized_pnl`, `marked_at` are absent.
- `ScanService.execute_buy` / `execute_sell` take keyword-only arguments
  (`market_id=`, `side=`, `shares=`).
- `TradeDialog` dismiss payload changed from `str | None` (trade UUID)
  to `dict | None` with `{"action", "side", "shares", ...}` on success.
  Truthy callers work unchanged; code reaching into the string does not.
- `scanner/auto_resolve.py` was removed. Resolution now lives in
  `scanner/daemon/resolution.py` and runs inside the poll job.

### Known Limitations

- Markets seeded before the beta that added `fees_enabled` / `fee_rate`
  columns will have both values as default (disabled, no rate) until the
  event is re-scanned. Re-adding the event URL refreshes the row with
  Gamma's current schedule.
- `WalletResetModal` sends SIGTERM to the scheduler daemon and waits 1
  second before clearing wallet tables, then auto-restarts on success.
  If a poll tick is mid-resolution at that moment the race is serialized
  by SQLite, but error reporting is raw. Plan is to harden with
  `BEGIN EXCLUSIVE` or a poll-wait before stable.
- `feeSchedule.exponent` is assumed to be 1 (matches all observed crypto /
  sports schedules). Non-linear curves, if Polymarket ships any, will
  require a formula update.

[Unreleased]: https://github.com/ShiyuCheng2018/polily/compare/v0.6.0-beta.1...HEAD
[0.6.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.6.0-beta.1
