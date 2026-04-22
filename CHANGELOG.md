# Changelog

All notable changes to Polily are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelog started at v0.6.0; prior versions (v0.5.x and earlier) have no
structured release notes — see `git log` for history.

## [Unreleased]

### Added

- `scanner/core/lifecycle.py` — market / event lifecycle state derivation. `MarketState` 4 states: TRADING / PENDING_SETTLEMENT / SETTLING / SETTLED, derived from `markets.closed` + `end_date` + `resolved_outcome`. `EventState` 3 states (ACTIVE / AWAITING_FULL_SETTLEMENT / RESOLVED) derived from child market states. Zero DB schema changes — purely a derive-on-read helper + label catalog + winner-suffix helper.
- `resolved_outcome` field exposed on `MarketRow` Pydantic model (`scanner/core/event_store.py`). DB column already existed; ORM layer was dropping it silently. No migration needed.
- `backfill_stuck_resolutions()` — daemon-startup one-time pass that heals legacy `closed=1 AND resolved_outcome IS NULL` rows left over from the pre-v0.8.5 `_has_positions` gate era. Capped at 100 rows per invocation so startup stays fast; remaining rows heal on subsequent restarts.

### Changed

- **Resolver: `scanner.daemon.poll_job._resolve_closed_market_if_position` no longer gates on user position.** `markets.resolved_outcome` is now written for every `closed=1` market whose Gamma UMA state reaches `resolved` with clean outcomePrices, regardless of whether the user had a position. Wallet credit is still position-gated inside `ResolutionHandler.resolve_market`. This brings the code in line with the module's docstring ("persisted even when the user held no positions — keeps the DB authoritative for replay / dashboards") and makes `resolved_outcome IS NULL` the unambiguous SETTLING-state signal for the lifecycle UI.
- `SubMarketTable` 结算 column: non-TRADING markets show state label (`[即将结算]` / `[结算中]` / `[已结算]`) instead of the misleading "已过期" countdown.
- `EventDetailView` 市场 zone title: multi-market events show `(活跃 N, 即将结算 N, 结算中 N, 已结算 N)`; binary events show single-state badge including winner for SETTLED (`(已结算 NO 获胜)`). SETTLED markets without `resolved_outcome` (legacy rows) fall back to `(已结算)` with no winner suffix.
- `EventKpiRow` 子市场 card: drops the `(N过期)` suffix — card is a plain total now, since breakdown lives in the 市场 zone title.
- `EventKpiRow` 结算 card: uses event lifecycle state (`待全部结算` / `已结算`) instead of `format_countdown_range` returning "已过期" for past dates.
- `EventHeader` on binary events: settlement line renders as a Rich-markup progress breadcrumb (`{countdown} | 即将结算 | 结算中 | 已结算`) with current state highlighted (`[b $primary]`), past states checkmark-dim (`[dim]... ✓[/]`), and future states plain dim (`[dim]...[/]`).
- `EventHeader` on multi-market events: settlement label switches to `待全部结算` / `已结算` once event state advances past ACTIVE.
- `monitor_list` 结算 column: uses event lifecycle state via a single aggregate `json_group_array` SQL query (no N+1 child loads); shows `待全部结算` / `已结算` instead of "已过期 ~ 已过期" range.
- `score_result` view: banner text derived from event state; replaces old `_is_expired` boolean path.
- `ScanService._query_events` returns a new `markets_summary` list per event (compact `{closed, end_date, resolved_outcome}` dicts) used by the monitor_list settlement cell.
- `ChangelogView` (更新日志 page) now shows a version header — `当前版本: vX · 最新稳定版: Y` — with the latest stable tag fetched asynchronously from GitHub releases on mount (and on `r` refresh). Offline / timeout fallback to `无法获取` so the page never blocks.

### Fixed

- `MarketRow` was silently dropping the DB `resolved_outcome` column due to ORM-schema drift (column existed in `scanner/core/db.py` but not in `_MARKET_ALL_COLS` tuple); now aligned, allowing lifecycle state to derive correctly from DB rows.
- `ChangelogView` page is now scrollable. Previously `PolilyZone { height: 1fr }` clamped the inner zone to the viewport, truncating long changelogs. Changed to `height: auto` so the outer `VerticalScroll` actually scrolls.

## [0.8.0] — 2026-04-22

### Added

- Design system foundations: spacing / color / typography tokens (`scanner/tui/css/tokens.tcss`)
- Polily-dark brand theme with semantic colors (`scanner/tui/theme.py`)
- `polily-geek` phosphor-green CRT theme as optional alternative (`Ctrl+P → Change theme`)
- Atom widget library under `scanner/tui/widgets/`: PolilyZone, PolilyCard, StatusBadge, KVRow (+ `set_value()`), EmptyState, LoadingState, SectionHeader, ConfirmCancelBar, QuickAmountRow, BuySellActionRow, FieldRow, AmountInput
- Nerd Font icon constants (`scanner/tui/icons.py`) and Chinese label translations (`scanner/tui/i18n.py`)
- EventBus pub/sub scaffold (`scanner/core/events.py`) with topic constants for scan/wallet/monitor/position/price
- `polily doctor` CLI subcommand — environment diagnostic (Nerd Font, terminal size, DB, Claude CLI, install hints)
- Q11 key binding spec (`scanner/tui/bindings.py`) — global / CRUD / navigation groups
- README Requirements section documenting Nerd Font dependency
- `docs/ui-guide.md` — user-facing UI reference
- `scripts/generate_snapshots.py` — release-QA helper that captures SVG/PNG snapshots of every view + modal for manual visual review (the lighter-weight alternative to `pytest-textual-snapshot`; see `docs/internal/v090-backlog.md` for the ROI discussion that descoped automated baseline diffing)
- **`ChangelogView`** — new 7th sidebar menu (`6` key) that renders `CHANGELOG.md` as Markdown inside the TUI so users can browse release notes without opening another tool. Ships bundled into the wheel via `pyproject.toml` `[tool.hatch.build.targets.wheel] force-include`; dev checkout takes precedence so `r` refresh shows live edits.
- `scanner/core/positions.py` `DUST_SHARE_THRESHOLD` + `is_dust_position()` — display layers now hide sub-0.1-share fragments left behind by partial sells.
- `scanner/tui/_dispatch.py` — `dispatch_to_ui(app, fn)` + `@once_per_tick` decorator (React-style coalescing).

### Changed

- `PolilyApp.theme` defaults to `polily-dark`; user can switch to Textual built-ins (`nord`, `dracula`, `textual-light`, etc.) via `Ctrl+P → Change theme`
- `ScanService.__init__` now accepts `event_bus` kwarg (backward compatible; defaults to `get_event_bus()` singleton)
- App-level `BINDINGS` now declares `q` / `?` / `Esc` globally
- `ScanService.topup` / `withdraw` now publish `TOPIC_WALLET_UPDATED` on success
- `scan_log` view migrated to v0.8.0 atoms (PolilyZone + StatusBadge + KVRow), Chinese status labels, EventBus subscription (no manual refresh), Q11 key bindings. Covers `ScanLogView` + `ScanLogDetailView` + `LiveProgress`. Top zone renamed `分析队列` → **`任务队列`** and now surfaces both `analyze` (分析) and `add_event` (评分) running rows; live label switches between `正在分析... / 正在评分...` based on task type. Columns split `类型` → `触发` (手动/定时/监控) + `类型` (分析/评分), 历史 7 列(加错误列). 详情页去掉 `scan_id` / `event_id` — 用户不再看到内部标识. `ScanLogView(service)` ctor refactor; `screens/main.py` 2 call sites updated.
- `wallet` view migrated to v0.8.0 atoms (PolilyCard + PolilyZone + KVRow), EventBus subscription to wallet/position topics. `t`/`w`/`r` 充值/提现/重置 bindings all `show=True` in footer.
- `market_detail` view migrated to v0.8.0 atoms (multiple PolilyZone: 事件信息/市场/持仓/叙事分析), EventBus subscription to price/position updates (price filtered by event_id), added `r` refresh binding.
- `monitor_list` view migrated (`ICON_AUTO_MONITOR` header, subscribes to 3 topics — monitor/price/scan — for live refresh).
- `market_list` view migrated (PolilyZone "研究列表", subscribes to price/monitor/scan; dead `get_research_events` reference fixed to `get_all_events`).
- `paper_status` view migrated (PolilyZone "持仓", subscribes to wallet/position; mount-once refresh pattern avoids Textual deferred-remove crash).
- `archived_events` view migrated (PolilyZone with `ICON_COMPLETED`, no bus subscription — historical snapshot).
- `history` view migrated (PolilyZone "历史", subscribes to `TOPIC_WALLET_UPDATED` for auto-refresh on SELL/RESOLVE).
- `score_result` view migrated (3-zone structure matching market_detail, no bus — one-shot snapshot).
- `trade_dialog` migrated — `TradeDialog` + `BuyPane` + `SellPane` all 3 classes wrapped in PolilyCard/PolilyZone; BuyPane gets `ICON_BUY`, SellPane gets `ICON_SELL`; subscribe to `TOPIC_PRICE_UPDATED` for live mid refresh while dialog open; kept 3s polling fallback for daemon-less sessions.
- `wallet_modals` migrated — `TopupModal` + `WithdrawModal` + `WalletResetModal`; Reset keeps `border: round $error` destructive visual + `⚠ 不可撤销` warning + `reset`-typed confirm input.
- `scan_modals.ConfirmCancelScanModal` migrated (PolilyZone + `border: round $error`).
- `monitor_modals.ConfirmUnmonitorModal` migrated (PolilyZone + `border: round $error`).
- `MainScreen` migrated with `TOPIC_SCAN_UPDATED` bus subscription — completed/failed scans pulse a "new" indicator on the 任务 sidebar pill when user isn't on that menu.
- `MainScreen` installs a 5s **bus heartbeat** (`_bus_heartbeat`) fanning out match-all payloads on PRICE/POSITION/WALLET/MONITOR/SCAN so cross-process daemon writes (the daemon's own bus is out of reach) reach subscribing views. Worst-case UI lag is 30s daemon poll + 5s heartbeat ≈ 35s; user can still hit `r` for instant DB re-read.
- `widgets/cards.py` (MetricCard + DashPanel) — legacy widgets preserved per Q7b scope, DEFAULT_CSS updated to pure theme vars (`$primary` / `$accent` / `$surface`).
- `widgets/sidebar.py` (Sidebar + SidebarItem) — each menu item now shows a Nerd Font icon via central `MENU_ICONS` map (tasks→scan, monitor→eye, paper→briefcase, wallet→money, history→check, archive→calendar).
- **Uniform footer `r 刷新` across every content view** — each view declares its own `Binding("r", "refresh", "刷新", show=True)` + `action_refresh`. `ScoreResultView` / `ScanLogView` / `ScanLogDetailView` gained the binding for the first time; existing ones flipped `show=False → True` so the footer surfaces the key. Covers 9 content views (event_detail / monitor_list / paper_status / wallet / history / archived_events / scan_log / scan_log_detail / score_result).
- **`o 链接` binding on detail pages** — `ScoreResultView` and `ScanLogDetailView` now match `EventDetailView`: pressing `o` opens the Polymarket event page in the system browser (`webbrowser.open`). Missing slug → warning toast rather than crash.
- **Wallet reset moved `r` → `shift+r`.** `r` is now page refresh (consistency across every view); reset keeps its mnemonic but requires the Shift modifier so destructive op doesn't fire on an accidental single key. Red 重置钱包 button preserved as the primary click target. Removed the `[t] 充值 [w] 提现 [r] 重置` hint Static in wallet view — Footer already shows every binding.
- **Trade guard**: `EventDetailView.action_trade` now blocks with a warning toast ("需要先激活监控才能进行交易 — 按 m 开启监控") when the event's `auto_monitor` is off. Opening a position on an unmonitored event would leave it without price polling, movement scoring, or narrator attention.
- `ScoreResultView` 市场 zone reuses `BinaryMarketStructurePanel` for binary events (parity with `EventDetailView`); multi-outcome events still use `SubMarketTable`.
- **Slogan rebrand** from "Polymarket Decision Copilot" to **"A Polymarket Monitoring Agent That Actually Works"** across TUI top bar, CLI help, package docstring, `pyproject.toml` description, and `CLAUDE.md`. Better matches Polily's day-to-day value — running in the background, polling prices, tracking movement, alerting on changes.
- **Display-layer dust filter** — `ScanService.get_open_trades` / `get_all_positions` / `get_event_detail["trades"]` hide positions with `shares < 0.1` (≈ <$0.10 max value) so paper_status, wallet balance card, and event_detail PositionPanel don't show 0.02-share partial-sell stragglers. Accounting layers (trade engine, narrator prompt, trade guard, monitor toggle) still see raw rows.

### Fixed

- Eliminated race-prone manual `_refresh_*` calls in migrated views — view state now derives from EventBus payloads, bus callback uses thread-safe `dispatch_to_ui` (see below).
- `PolilyZone` title ordering — was appearing at bottom of zone when composed via `with PolilyZone():` context manager; now mounted at index 0 via `on_mount()` to force top position.
- `market_detail` VerticalScroll no longer overflows — added `height: 1fr` / `height: auto` CSS pair; analysis zone no longer covers other zones.
- `PositionPanel` dropped redundant inner DashPanel wrapper (outer PolilyZone "持仓" was being duplicated).
- Event meta row (`political | 结算 | 监控 | 共识异动`) given vertical breathing room separating from title above and KPI cards below.
- **`ScoreResultView._is_expired` uses `event.closed` (Polymarket's authoritative close flag) instead of `end_date < now`.** Multi-market events whose primary end date has passed but whose sub-markets are still tradable no longer show "事件已过期".
- **EventBus publisher gaps closed.** Pre-fix only `topup`/`withdraw` published `TOPIC_WALLET_UPDATED` and `analyze_event` published `TOPIC_SCAN_UPDATED` — other topics had zero producers, so views subscribing to `PRICE`/`POSITION`/`MONITOR` listened to silence. Now `ScanService.execute_buy` / `execute_sell` publish POSITION + WALLET, `ScanService.toggle_monitor` publishes MONITOR.
- **Silent bus-callback swallow on UI thread.** `App.call_from_thread` raises `RuntimeError` when called from the event-loop thread, and `EventBus.publish` catches handler exceptions — so any publisher running on the UI thread (user button click, heartbeat, modal dismiss) saw its view refresh silently dropped. Visible "refresh after topup" only worked because `_on_modal_dismissed` called `refresh_data` directly. Added `scanner.tui._dispatch.dispatch_to_ui(app, fn)` which delegates to Textual's own thread check (`try: call_from_thread; except RuntimeError: call_later(0, fn)`); replaced all bus-handler `call_from_thread` calls across event_detail / wallet / history / paper_status / monitor_list / scan_log / trade_dialog / main.
- **DuplicateIds crash on manual `r` refresh.** `MonitorListView._render_all` and `ScanLogView._rebuild_*_zone` used `for child in zone.query(DataTable): child.remove()` followed by immediate `zone.mount(DataTable(id=...))`. Textual's `remove()` is deferred; on sync key-press paths the new mount raced the pending removal and crashed with `DuplicateIds('monitor-table')` / `upcoming-table`. Bus callbacks went through `call_from_thread` so the race rarely surfaced there. Fix: mount-once pattern (same as History/PaperStatus/ArchivedEvents) — mount DataTable in `on_mount`, then `table.clear()` + re-add rows on refresh.
- **`_refresh_current_view` half-silent path removed.** Pre-fix the 5s poll heartbeat tried to call `.refresh_data()` on the active view but only 4 of 9 views defined that method. The other 5 silently no-op'd. Now view refresh goes entirely through the bus heartbeat, which covers every subscribing view.
- **React-style coalescing via `@once_per_tick`.** Added a decorator in `scanner/tui/_dispatch.py` that turns N synchronous same-tick calls into 1 deferred execution (same principle as React 18 automatic batching). Applied to `refresh_data` on EventDetailView and `_render_all` on MonitorListView / PaperStatusView / WalletView. Heartbeat fan-out (5 topics → 3 handlers subscribing to different subsets) used to trigger `_render_all` up to 3× per view per tick; now 1×. Initial `on_mount` renders bypass the decorator via `type(self)._render_all.__wrapped__(self)` so callers/tests see synchronous population.
- **`ScanService.execute_buy/sell` guards with `MonitorRequiredError`.** Service layer (not TradeEngine — engine stays a pure atomic primitive) asserts `events.auto_monitor=1` before delegating to the engine. Primary UI guard in `EventDetailView.action_trade` still fires first (better UX — block the dialog from opening); service-layer guard is defence-in-depth for future autopilot paths or DB-drift edge cases. Any future caller (live-money trading service) MUST replicate this check or route through `ScanService`. `TradeDialog` BuyPane / SellPane `buy_confirmed` / `sell_confirmed` handlers now specifically catch `MonitorRequiredError` and surface the same warning toast.
- **Heartbeat payload uses explicit `source="heartbeat"` sentinel.** `EventDetailView._on_price_update` and `TradeDialog._on_price_update` previously treated a missing `event_id` as match-all — risked silently accepting any publisher that forgot the key. Now checks `payload.get("source") == "heartbeat"` explicitly; ambiguous payloads (no event_id, no heartbeat sentinel) are filtered out.
- **`WalletView` balance card uses stable widget IDs.** The 5 KVRows (`#wallet-cash` / `#wallet-available` / `#wallet-positions-value` / `#wallet-unrealized` / `#wallet-realized`) and 2 `.wallet-dynamic` Statics (`#wallet-headline` / `#wallet-footnote`) mount once in `on_mount`; `_render_balance_card` now updates in place via `KVRow.set_value()` (new atom method) and `Static.update()`. Removes the prior remove+remount pattern that could briefly double-display rows under rapid bus callbacks.
- **Narrator failures no longer masquerade as "completed".** Pre-fix, any `claude` CLI retry-exhaustion or schema-invalid output was silently replaced by a fake `NarrativeWriterOutput` with `summary="AI 分析不可用..."`. `ScanService.analyze_event` treated that as success → `finish_scan(completed)` + stored a bogus analysis version. Now both failure paths raise; `analyze_event`'s existing exception handler correctly marks the scan_logs row `failed` and skips `append_analysis`. Dropped `narrative_fallback()` + `_fallback_from_prompt()` as dead code.
- **`scan_log` history 结束时间 column** was slicing `finished[-5:]` which grabbed "SS:00" (the last 5 chars of `YYYY-MM-DD HH:MM:SS`) instead of "HH:MM". Now formats as `YY-MM-DD HH:MM`.

### Limitations

- Nerd Font is now a hard dependency. Users without Nerd Font will see `□` tofu boxes. `polily doctor` provides install guidance.
- Minimum terminal size: 100×30. Below this, wrapping may occur.
- Design system documentation (`docs/design-system.md`) deferred to v0.8.1.
- Legacy view overlap (`paper_status` / `wallet`; `history` / `scan_log` history zone) not consolidated. v0.9.0 decision.
- `EventBus` is process-local. The daemon process runs `poll_job` every 30s and writes `markets.yes_price` / `events.structure_score` / `positions` / `wallet_transactions` to SQLite, but publishes to ITS OWN bus — the TUI process never receives those events. Bridged by MainScreen's 5s `_bus_heartbeat` which fans out match-all payloads on every bus topic, triggering views to re-read DB. Worst-case UI lag is therefore 30s daemon poll + 5s heartbeat ≈ 35s; `r` forces an instant DB re-read. See `docs/ui-guide.md` Developer notes.
- `pytest-textual-snapshot` automated visual regression tests were evaluated and descoped for v0.8.0 (ROI too low for a solo-user TUI with active Textual-version churn). Manual QA uses `scripts/generate_snapshots.py`. See `docs/internal/v090-backlog.md` for the analysis.

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

[Unreleased]: https://github.com/ShiyuCheng2018/polily/compare/v0.8.0...dev
[0.8.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.8.0
[0.7.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.7.0
[0.6.1]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.6.1
[0.6.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.6.0
