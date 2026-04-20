# Changelog

All notable changes to Polily are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelog started at v0.6.0; prior versions (v0.5.x and earlier) have no
structured release notes — see `git log` for history.

## [Unreleased]

### Added

- Design system foundations: spacing / color / typography tokens (`scanner/tui/css/tokens.tcss`)
- Polily-dark brand theme with semantic colors (`scanner/tui/theme.py`)
- Atom widget library under `scanner/tui/widgets/`: PolilyZone, PolilyCard, StatusBadge, KVRow, EmptyState, LoadingState, SectionHeader
- Nerd Font icon constants (`scanner/tui/icons.py`) and Chinese label translations (`scanner/tui/i18n.py`)
- EventBus pub/sub scaffold (`scanner/core/events.py`) with topic constants for scan/wallet/monitor/position/price
- `polily doctor` CLI subcommand — environment diagnostic (Nerd Font, terminal size, DB, Claude CLI, install hints)
- Q11 key binding spec (`scanner/tui/bindings.py`) — global / CRUD / navigation groups
- README Requirements section documenting Nerd Font dependency

### Changed

- `PolilyApp.theme` defaults to `polily-dark`; user can switch to Textual built-ins (`nord`, `dracula`, `textual-light`, etc.) via `Ctrl+P → Change theme`
- `ScanService.__init__` now accepts `event_bus` kwarg (backward compatible; defaults to `get_event_bus()` singleton)
- App-level `BINDINGS` now declares `q` / `?` / `Esc` globally
- `ScanService.topup` / `withdraw` now publish `TOPIC_WALLET_UPDATED` on success
- `scan_log` view migrated to v0.8.0 atoms (PolilyZone + StatusBadge + KVRow), Chinese status labels, EventBus subscription (no manual refresh), Q11 key bindings. Covers `ScanLogView` + `ScanLogDetailView` + `LiveProgress`. 分析队列 5 列(类型/状态/事件/预定时间/原因), 历史 6 列(加错误列). 详情页去掉 `scan_id` / `event_id` — 用户不再看到内部标识. `ScanLogView(service)` ctor refactor; `screens/main.py` 2 call sites updated.
- `wallet` view migrated to v0.8.0 atoms (PolilyCard + PolilyZone + KVRow), EventBus subscription to wallet/position topics. `t`/`w`/`r` 充值/提现/重置 bindings all `show=True` in footer.
- `market_detail` view migrated to v0.8.0 atoms (multiple PolilyZone: 事件信息/市场/持仓/叙事分析), EventBus subscription to price/position updates (price filtered by event_id), added `r` refresh binding.

### Fixed

- Eliminated race-prone manual `_refresh_*` calls in migrated views — view state now derives from EventBus payloads, bus callback uses `call_from_thread` per v0.8.0 threading convention.

## [0.7.0] — 2026-04-20

### Scheduler rework (DB-backed dispatcher)

- **APScheduler downgraded to heartbeat only.** The daemon no longer
  holds in-memory date jobs for scheduled AI analyses. Every 30s poll
  tick scans `scan_logs` for overdue `status='pending'` rows and
  dispatches them to the `ai` executor. Laptop sleep / process kill
  / launchd restart all become no-ops: the next tick picks up
  overdue work from the DB. Solves the recurring "missed scheduled
  check after Mac was closed overnight" bug.
- **Menu 0 split into `分析队列` / `历史` zones.** Pending and
  running AI analyses surface at the top with their schedule or live
  timer; completed / failed / cancelled / superseded fall to history.
  Running rows compute elapsed time live from `started_at` at render.
  The 历史 zone adds a `类型` column so AI 分析 / 评分 / 扫描 rows
  can be distinguished at a glance.
- **`c` on a running row in 分析队列** opens a confirmation modal to
  cancel the in-flight analysis. For TUI-initiated runs the Claude CLI
  subprocess is killed and the row flipped to `cancelled`. For rows
  initiated by the daemon's dispatcher (scheduled / movement triggers)
  the DB row is flipped to `cancelled` and the subsequent narrator
  completion is safely ignored — the daemon subprocess still runs to
  natural end but its result is discarded and no phantom pending row
  is emitted. Process-local `narrator_registry` means true subprocess
  termination from the TUI for daemon runs is not yet implemented;
  planned for a later release via DB-backed cancel signals.
- **Movement-triggered analyses** no longer bypass the queue — they
  write a pending row with `trigger_source='movement'` and go through
  the same dispatcher as scheduled runs. All AI triggers (manual /
  scheduled / movement) now share one lifecycle.
- **Crash recovery.** On daemon startup, any `scan_logs` row stuck
  at `status='running'` (left over from a crash) is marked `failed`
  with `error='进程中断，未完成'` — the user sees the row
  in history and decides whether to retry.
- **Monitoring toggle cleanup.** Turning `auto_monitor` off for an
  event now supersedes all its pending scan_logs rows atomically, so
  a closed monitor won't silently fire a queued analysis.
- **Exception type preservation**: agent failures surface in
  `scan_logs.error` as `"RuntimeError: Claude crashed"` instead of
  just the message, so debugging can distinguish transient from
  structural failures.

### Breaking (library callers only)

- `event_monitors.next_check_at` and `next_check_reason` columns
  dropped. All scheduling lives in `scan_logs` now; migration is
  automatic on first DB open of an upgraded install (existing pending
  schedules are seeded into scan_logs as pending rows).
- `scanner.daemon.notify` module removed. SIGUSR1 handler gone.
  `update_next_check_at` removed from `scanner.core.monitor_store`.
- `WatchScheduler.schedule_check / cancel_check / list_pending /
  restore_check_jobs` removed. Callers should insert a `scan_logs`
  pending row via `scanner.scan_log.insert_pending_scan`.
- New helpers exposed in `scanner.scan_log`: `insert_pending_scan`,
  `claim_pending_scan`, `finish_scan`, `supersede_pending_for_event`,
  `fetch_overdue_pending`, `fail_orphan_running`.
- New module `scanner.agents.narrator_registry` for cross-process
  narrator cancellation (`register` / `unregister` / `cancel` by
  `scan_id`).

### Fixed

- Latent bug in `scanner/daemon/scheduler.py` `_execute_check` (deleted
  in this release) passed `db` positionally as `config` to ScanService
  — fixed en route to the deletion.

## [0.6.1] — 2026-04-19

Monitoring lifecycle v2 — the "monitor" flag now carries real user intent
through event close, positions guard users against accidentally abandoning
stakes, and the Notifications page retires in favor of a proper Archive
view. Supporting cleanup: shared `close_event` routine, dropped the
`notifications` table, and the Watchlist redesign shipped with this bundle.

### Added

- **Confirm-before-disable monitor + positions guard**: pressing `m` on a
  monitored event now asks for explicit confirmation before flipping off
  (`[确认取消]` / `[继续监控]` modal). When the event has any open
  position (YES or NO across any sub-market), the toggle-off is blocked
  outright — closing monitoring would stop polling, stop auto-resolution,
  and silently orphan the user's skin in the game. The block surfaces as
  an inline warning (`无法取消监控 — 该事件有 N 个持仓未结算`) and leaves
  `auto_monitor=1`. Rule applies consistently across MarketDetailView and
  Watchlist. Enabling monitor is unchanged (no confirmation, non-
  destructive). Service layer also raises `ActivePositionsError` as a
  defence-in-depth check.
- **Archive view (menu 5 `归档`)**: replaces the former "通知" page. Lists
  events the user was monitoring when they closed (`events.closed=1 AND
  event_monitors.auto_monitor=1`), sorted by close time. Columns: 事件 /
  结构分 / 子市场 / 关闭于. Row click navigates to `MarketDetailView`,
  which also closes the "no way to re-open a closed event's detail" UX
  gap noted in the v0.6.0 follow-up list.

### Changed

- **Watchlist (TUI menu 1) redesigned**: scoped tightly to "what am I
  monitoring and when's the next poll" plus a few routing hints. The
  always-"监控中" status column was dropped. New columns: 结构分 (routing
  signal), AI版 (analysis version count), 异动 (latest tick rollup), 结算
  (settlement window across non-closed sub-markets, e.g.
  `2天6小时 ~ 40天16小时`). Next-check column expanded to
  `2026-04-21 09:00 (1d 11h 30m)` — full ISO date + compact relative
  time. Movement cell reuses the same roll-up semantics as the
  detail-page movement widget (max-M/max-Q of the latest tick's per-
  market rows, ignoring the event-level aggregate row poll_job writes
  last) and shares its magnitude-driven red/yellow/green palette.
  Data columns like position / leader price / P&L stay on their
  dedicated pages (Positions / Wallet / Market Detail), keeping page
  responsibilities non-overlapping.

### Removed

- **`notifications` table and module entirely.** The old system only ever
  wrote `[CLOSED]` rows from the close path — the Archive view derives
  that state from `events + event_monitors` directly, so the table,
  `scanner/notifications.py`, and `NotificationListView` all retired.
  `DROP TABLE IF EXISTS notifications` runs on first launch of an
  upgraded DB (idempotent, no-op on fresh installs). External callers
  of `scanner.notifications.*` or `ScanService.get_unread_notification_count`
  will need to migrate — these were never a public-API contract.

### Fixed

- **`auto_monitor` is now a stable user-intent flag, preserved through
  event close.** The v0.6.0 close paths flipped `auto_monitor=1` → `0`
  when an event closed, treating the field as "currently being polled"
  rather than "the user chose to monitor this event". That lost the
  information the upcoming Archive view needs ("events I was monitoring
  when they closed"). `close_event()` no longer touches `auto_monitor`;
  the Watchlist (`WHERE closed=0`) and poll guard (`if event.closed`)
  already prevent closed events from being polled, so the flag's value
  is now purely about user intent. `recheck_event` gained an early
  `if event.closed: return` gate so the still-scheduled rechecks on
  closed events no-op instead of re-firing `[CLOSED]` notifications.
- **Poll-path auto-close now emits a `[CLOSED]` notification**, matching
  the recheck close path that has always done so. Previously the poll
  path only updated `events.closed=1`, silently closing events the user
  was actively monitoring. Extracted the close routine into a shared
  `scanner/daemon/close_event.close_event()` and both paths call it, so
  the notification is emitted exactly once per closed event (poll gate
  on `event.closed == 0` prevents re-fire on subsequent ticks).

## [0.6.0] — 2026-04-19

Wallet system — paper trading gets real. Buys and sells now settle against
a single cash balance, positions aggregate across trades, and markets
auto-resolve when Polymarket publishes outcomes.

Shipped as `v0.6.0-beta.1` and stabilized as `v0.6.0` on 2026-04-19.

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
- **Binary event structure panel**: binary (single-market) events on the
  detail page now show the same 5-dimension score breakdown + per-dim
  commentary that multi-market events expose via row expansion. Flat
  layout (label / bar / score / comment) plus an overall summary line.
  `SubMarketTable` still owns multi-market rendering.

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
  by SQLite, but error reporting is raw. Will be hardened with
  `BEGIN EXCLUSIVE` or a poll-wait in a follow-up release.
- `feeSchedule.exponent` is assumed to be 1 (matches all observed crypto /
  sports schedules). Non-linear curves, if Polymarket ships any, will
  require a formula update.

[Unreleased]: https://github.com/ShiyuCheng2018/polily/compare/v0.7.0...dev
[0.7.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.7.0
[0.6.1]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.6.1
[0.6.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.6.0
