# Changelog

All notable changes to Polily are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelog started at v0.6.0; prior versions (v0.5.x and earlier) have no
structured release notes — see `git log` for history.

## [Unreleased]

## [0.6.0] — 2026-04-18

Wallet system — paper trading gets real. Buys and sells now settle against
a single cash balance, positions aggregate across trades, and markets
auto-resolve when Polymarket publishes outcomes.

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
- **Polymarket-accurate taker fees**: per-category curve
  (Crypto 7.2% ×p×(1−p), Sports 3%, …, Geopolitics / World Events 0%).
  Paper P&L now matches what you'd pay live.
- **Auto resolution**: `poll_job` detects closed markets with positions,
  fetches `outcomePrices` from Gamma, and settles through
  `ResolutionHandler` in one transaction — cash credited, position row
  deleted, audit line logged.
- **New TUI Wallet page** (menu `3`): balance panel (equity / cash /
  positions market value / realized / unrealized / ROI), recent
  transactions ledger, top-up / withdraw / reset actions.
- **`polily reset --wallet-only`**: CLI flag to wipe wallet-side tables
  without losing events, markets, or AI analyses.
- **Markets.resolved_outcome column**: structured per-market winner
  (`yes` / `no` / `invalid` / NULL), populated during resolution.

### Changed

- **TUI menu renumber**: `钱包` inserted at slot `3`; `历史` shifted to `4`,
  `通知` to `5`.
- **`paper_trades` is now read-only legacy**. All new writes go to
  `positions` and `wallet_transactions`. Migration runs automatically on
  first launch and aggregates existing open paper_trades into positions.
- **`narrative_writer.md` prompt**: now reads `wallet`, `positions`,
  `wallet_transactions` (was `paper_trades`). Adds "全方位管理" guidance
  so the agent can give position-sizing and correlation-risk advice
  based on the full wallet context.

### Fixed

- **Pre-existing agent bug**: `narrative_writer.md` had been SELECTing
  three non-existent columns from `paper_trades` (`exit_price`,
  `realized_pnl`, `created_at`). Agent silently swallowed the
  OperationalError and proceeded without trade history; fix migrates to
  the new schema and the history flows through correctly.

### Breaking Changes (v0.5.x → v0.6.0)

Migration is automatic for end users — these affect only callers of
`scanner` as a library.

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

- Positions migrated from pre-v0.6.0 `paper_trades` inherit the event's
  `polymarket_category`. If the event was added before v0.6.0 and
  `polymarket_category` was never populated, the first sell will use the
  default 0.05 fee rate even for Crypto events (which should be 0.072).
  Workaround: re-add the event via URL to refresh the category before
  selling.
- `WalletResetModal` sends SIGTERM to the scheduler daemon and waits 1
  second before clearing wallet tables. If a poll tick is mid-resolution
  at that moment, the race is serialized by SQLite but error reporting
  is raw. Future hardening will pause the scheduler explicitly.

[Unreleased]: https://github.com/ShiyuCheng2018/polily/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.6.0
