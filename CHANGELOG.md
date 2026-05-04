# Changelog

All notable changes to Polily are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelog started at v0.6.0; prior versions (v0.5.x and earlier) have no
structured release notes — see `git log` for history.

## [Unreleased]

## [0.11.4] — 2026-05-05

### Fixed

- **Dispatcher exception path now finalizes scan_logs row.** Pre-v0.11.4 if `_run_pending_analysis` raised before reaching `analyze_event` (e.g., `PolilyService.__init__` failing or `sqlite3.InterfaceError` from concurrent DB access), the outer try/except logged the trace but did NOT mark the scan_logs row as failed — left in `running` indefinitely until next daemon restart. Real prod incident 2026-05-04 21:38: 2 rows stuck running 12+ minutes. v0.11.4 broadens the try block to wrap the full function and explicitly calls `finish_scan(status='failed', error=...)` on exception, with a belt-and-suspenders nested try so a finish_scan failure can't crash the ai executor thread.
- **PolilyDB serializes ai-executor concurrent access.** Two ai executor threads racing `db.conn.execute()` produced `sqlite3.InterfaceError: bad parameter or other API misuse` (verified in `daemon-stderr.log` thanks to v0.11.2's redirect fix). v0.11.4 adds a single `threading.RLock` to `PolilyDB` and wraps the entire body of `_run_pending_analysis` with it. Other code paths (sidebar reads, daemon poll loop, manual TUI scans) are unchanged — broad migration to thread-safe wrappers across all 152 `db.conn.execute` call sites is deferred to v0.11.5.
- **httpx market-fetch: split timeouts + tenacity retry + per-tick circuit breaker.** Pre-v0.11.4 used `httpx.AsyncClient(timeout=15)` which set `read=15s` — the dominant tail under Polymarket CLOB load (76.8% poll error rate observed in v0.11.3 dogfooding). v0.11.4: split timeouts (`connect=5s, read=10s, write=10s, pool=10s`); per-market `_fetch_one` retries up to 3× with exponential backoff on `ConnectError` / `TimeoutException`; circuit breaker aborts retries for the rest of the tick after 5 consecutive ConnectErrors to prevent retry-storm under sustained outage.

### Added

- **Update available indicator on TUI sidebar.** Yellow `*` appears on 更新日志 entry when a newer PyPI version is available than the current installation. Click 更新日志 → background fresh PyPI fetch → mark current latest as seen → `*` disappears until a newer release ships. Cache TTL 6h; network failures silent. Reuses the existing `mark_new_data` infrastructure (same indicator as 任务记录 / 监控). New dep: `packaging>=24.0,<26.0` for PEP 440-correct version comparison.

### Notes

Reliability + UX bundle. No schema migrations; one new HIDDEN_IN_TUI config leaf (`update_check.last_dismissed_version`) auto-seeded on first run. v0.11.x → v0.11.4 upgrade is `pipx upgrade polily`.

## [0.11.3] — 2026-05-04

### Fixed

- **Daemon auto-launch under launchd.** v0.11.2 set `KeepAlive: {Crashed: True}` thinking it meant "restart on crash, respect clean stops". Apple's actual semantic: "the daemon should be running ONLY IF the previous exit was a crash" — on `launchctl load` there is no previous exit, so the condition is false and the daemon never starts. Symptom: TUI launch regenerated the plist correctly + `launchctl load` returned success, but daemon stayed at PID `-`. v0.11.3 reverts to `KeepAlive: True` (always alive) — daemon starts on load, restarts on any exit, and `polily scheduler stop` still cleanly unloads the agent without respawn (because `launchctl unload` removes the agent from launchd's registry entirely).

### Notes

Hotfix-of-hotfix patch. No code changes besides the plist `KeepAlive` value (and the corresponding test assertions). Restores the v0.11.0 / v0.11.1-era "TUI launch auto-restarts daemon" product behavior. Existing pipx users should `pipx upgrade polily`.

## [0.11.2] — 2026-05-04

### Fixed

- **`phrases.yaml` packaging.** v0.11.1 wheel was missing `polily/config/phrases.yaml` (file was at `config/phrases.yaml` repo root, not inside the package). Pipx-installed polily crashed on first event scoring with `[Errno 2] No such file or directory`. v0.11.2 migrates the file into the `polily.config` subpackage and uses `importlib.resources` for resolution (install-method-agnostic).
- **Daemon auto-restart.** Pre-v0.11.2 launchd plist used `KeepAlive: {SuccessfulExit: False}` which did NOT restart on clean SIGTERM exit-0. v0.11.2 switches to `KeepAlive: {Crashed: True}` so the daemon auto-recovers from crashes/OOM/SIGKILL while still respecting `polily scheduler stop` (which uses `launchctl unload` — no respawn).
- **Daemon stderr no longer swallowed.** Pre-v0.11.2 launchd plist routed stderr to `/dev/null`, hiding all `logger.exception` traces. v0.11.2 redirects to `<log_dir>/daemon-stderr.log` so future exception diagnoses are possible.

### Added

- Regression test (`tests/test_packaging_resources.py`) that loads packaged YAML resources via the same `importlib.resources` pattern runtime uses — catches future packaging-bug regressions across editable + pip + pipx install methods.

### Notes

This is a hotfix patch — no breaking changes, no schema changes. v0.10.x → v0.11.0 migration semantics unchanged. Existing pipx users should `pipx upgrade polily`. Existing dev (editable) installs need no action.

## [0.11.1] — 2026-05-04

### Added

- **PyPI distribution.** `pipx install polily` now works. Previous installation flow (`git clone` + `pip install -e .`) still works for contributors but is no longer the recommended path for end users.
- **Trusted Publishing via GitHub OIDC.** No long-lived PyPI API token to rotate; each release fetches a short-lived publish token from PyPI's OIDC verifier on a per-run basis.

### Notes

This is a distribution-only release — no runtime behavior changes vs. v0.11.0. Existing v0.10.x → v0.11.0 migration semantics still apply unchanged.

## [0.11.0] — 2026-05-04

### BREAKING

- **Default data location moved to OS-standard path.** Pre-v0.11.0, polily wrote `data/polily.db` (and logs, yaml snapshot) relative to the directory polily was launched from — convenient for dev, but broken for any non-developer install (`pipx`, Homebrew, binary). v0.11.0 resolves all paths via the new `polily.core.paths` module:
    - **macOS:** `~/Library/Application Support/polily/`
    - **Linux:** `$XDG_DATA_HOME/polily` or `~/.local/share/polily/`
    - Override with `POLILY_DATA_DIR=...` env var or `polily --data-dir=...` CLI flag (highest priority).
- **Logs colocated with data by default.** `paths.log_dir()` is `data_dir()/logs` unless `POLILY_LOG_DIR` is set. Single env var (`POLILY_DATA_DIR`) controls everything.
- **Launchd plist Label is now env-overridable.** `POLILY_LAUNCHD_LABEL` defaults to `com.polily.scheduler` (matches v0.10.x); set to `com.polily.scheduler.dev` for dev daemons that must coexist with prod.
- **`archiving.db_file` Pydantic config knob is now informational-only.** Pre-v0.11.0 the `default_db_path()` function read this knob's Pydantic default. Now it delegates to `paths.db_path()`. The knob remains in the schema for forward compat (HIDDEN_IN_TUI per Whis SF11) but no production code path reads it.
- **`agent_feedback.log` + `agent_debug.log` paths use paths module.** Pre-v0.11.0 these wrote to `os.getcwd()+"data/logs"` (import-time captured `_DEBUG_DIR`). Now `paths.log_dir()`. Old logs at the cwd-relative path are not migrated; users keep them where they are.
- **Agent prompt uses `$POLILY_DB` env var.** `polily/agents/prompts/narrative_writer.md`'s 11 `sqlite3 data/polily.db` invocations now read `sqlite3 "$POLILY_DB"`. The claude CLI subprocess inherits `POLILY_DB=str(paths.db_path())` from the parent.
- **Daemon poll log file at `paths.log_dir()/poll-v<version>-<TS>.log`.** Pre-v0.11.0 `polily/daemon/poll_job.py` computed `Path(__file__).resolve().parent.parent.parent / "data" / "logs"` which would crash on pipx-installed daemons (site-packages is read-only).

### Migration guide

⚠ **Pre-flight: stop the v0.10.x daemon before upgrading.** The daemon polls `./data/polily.db` every 30s; if it's still alive while v0.11.0 migrates the file, you risk a torn WAL copy or post-migration state divergence. Run `polily scheduler stop` BEFORE `pip install`.

On first launch, v0.11.0 detects `./data/polily.db` (your legacy install) and prompts:

```
[polily v0.11.0] 检测到旧版数据库:
  /your/repo/data/polily.db
polily 现在将数据保存到:
  /Users/you/Library/Application Support/polily/polily.db
是否复制旧数据到新位置? [Y/n]:
```

Press Enter (default Y) to copy your wallet, monitored events, and analysis history. The legacy file is left untouched; a `.migrated_to_v0.11.0` marker prevents re-prompts on subsequent launches.

If the migration partially fails (e.g., disk full mid-WAL-copy), polily cleans up the partial copy at the new path so you can retry on next launch — the marker is NOT written until copy succeeds.

If you decline (N), polily starts with an empty new db. Manual migration later: `cp /your/repo/data/polily.db* ~/Library/Application\ Support/polily/`.

After migration: `polily scheduler restart` to re-register the daemon at the new path.

### Added

- **`polily.core.paths` module — single source of truth for all on-disk paths.** Three-layer resolver (CLI flag > env var > platformdirs default), lazy mkdir, env-overridable launchd label. Public API: `data_dir()`, `log_dir()`, `db_path()`, `agent_feedback_log()`, `agent_debug_log()`, `launchd_label()`, `launchd_plist_path()`, `legacy_data_dir()`, `legacy_db_path()`, `set_data_dir_override(p)`, `set_log_dir_override(p)`.
- **CLI flags `--data-dir` and `--log-dir`** at the top level (`polily`, `polily scheduler run`, `polily reset`). Flags override the env-var tier. Useful for ad-hoc tests like `polily --data-dir=/tmp/test ...`. When `--data-dir` is set, the v0.11.0 first-launch migration prompt is automatically skipped (user has declared intent).
- **`.envrc.example` for direnv users.** Activate repo-local data dir + dev launchd label with `cp .envrc.example .envrc && direnv allow`. README "Development" section documents the workflow.
- **First-launch v0.10.x → v0.11.0 migration prompt.** New `polily.core.migration_v0_11_0` module + TUI bootstrap integration. Daemon launchd context never auto-migrates (interactive contexts only). Marker file suppresses re-prompts. Partial-copy failures auto-cleanup so retry works.
- **`platformdirs>=4.0,<5.0` dependency.** Standard library substitute for OS-specific path conventions.

### Internal

- **Test fixture `polily_db` is now additive (chdir + setenv).** Per Whis-review S8, keeps backward compat with cwd-asserting tests AND drives the new env-based resolver. No tests broke during migration.
- **Launchd plist `EnvironmentVariables` propagates `POLILY_DATA_DIR` (always) and `POLILY_LOG_DIR` (when explicitly set)** so the daemon's path resolution agrees with the parent process that registered the plist.
- **Defense-in-depth `_block_real_launchd_writes` autouse fixture in `tests/conftest.py`** redirects `Path.home()` to a per-test sandbox. Prevents tests from writing the user's real `~/Library/LaunchAgents/com.polily.scheduler.plist` even if a test path bypasses explicit mocks. Caught a pre-existing latent bug in `test_reset_modal_sigterms_daemon_before_reset` that did not mock `restart_daemon`.
- **Cross-platform: Linux XDG paths verified via platformdirs mock test** (`tests/test_paths_linux_xdg.py`). Real-Linux CI runner is a follow-up (separate PR / v0.11.x).

## [0.10.1] — 2026-05-02

### Fixed

- **Event detail page no longer jumps to top on 5-second heartbeat refresh.** Each child widget (header / KPI row / market table / movement chart / position panel / analysis panel) now has an in-place `update_data` method; `refresh_data` orchestrates per-child updates so `EventDetailView` itself is never recomposed. The outer `VerticalScroll`'s scroll position is preserved while you read long narratives. Mirrors the v0.10.0 R5 ConfigView in-place fix at commit `ad27e0f`.
- **Sidebar `监控列表 (N)` count no longer double-counts closed events.** `get_monitor_count()` now joins the events table and filters `closed=0`, mirroring the symmetric filter already in `get_archived_events()`. Pre-fix users with closed-but-still-monitored events saw `(N)` inflated by the archive count.
- **Daemon startup banner `X markets, poll every 30s` now matches what the daemon actually polls.** SQL now joins `event_monitors` with `auto_monitor=1`, mirroring `_get_monitored_markets` in `poll_job.py`. Pre-fix the banner counted phantom markets from previously-scanned-but-no-longer-monitored events; the number drifted higher than the real `clob N markets` poll line over time.
- **Hidden empty glossary collapsible in family weight modal.** When no signals in the current family match `_signals_glossary` entries, the entire `信号术语速查` Collapsible is now skipped instead of showing a placeholder line.

### Internal

- **`agent_feedback.log` header now includes `trigger={manual,scan,scheduled,movement}` + dual UTC/local timestamps.** Cross-timezone post-mortem debugging is much easier — local timestamp answers "when did the user actually see this?", trigger source answers "did the user request this or did the daemon dispatch it?". Trigger labels and `local:` label both stay English for grep-friendliness.
- **Direct unit tests for `_resolve_field_annotation` and `_coerce_value`.** 19 cases (35 invocations after parametrization) covering type resolution, scientific-notation int rejection, full bool truthy/falsy/garbage matrix, unknown-annotation rejection. Closes Vegeta R3 review test-coverage gap.

## [0.10.0] — 2026-05-01

### BREAKING

- **db.config is now the only config source.** Users edit via `polily → ⚙ 配置`. `config.yaml` is regenerated as a read-only snapshot on every polily startup; manual edits to `config.yaml` are silently overwritten.
- **`polily scheduler run --config <path>` flag deleted.** The daemon reads from `data/polily.db`'s `config` table at startup. Use the TUI for daily editing or `polily config reset` for emergencies.
- **`config.example.yaml` and `config.minimal.yaml` deleted.** Per-knob documentation lives in `polily/core/config_docs/*.md`.
- **First-run upgrade behavior:** existing `config.yaml` is auto-migrated to `db.config` on first v0.10.0 launch — your customizations are preserved. If yaml fails Pydantic validation, it's rescued as `config.yaml.bak` (NOT overwritten), defaults are loaded, and a stderr warning is emitted so you can manually rescue values.
- **Wallet `starting_balance` migration caveat:** if you previously customized `wallet.starting_balance` in `config.yaml` (e.g., `250.0`), the **knob value** is migrated correctly into `db.config`, BUT your wallet row is seeded with the Pydantic default (`100.0`) before migration runs on first launch. Run `polily reset --wallet-only` after the first v0.10.0 launch to reseed at your customized starting balance. (Users who never edited `wallet.starting_balance` are unaffected — the default matches.)
- **Pre-v0.9.x plist auto-migration:** users upgrading from old polily versions whose launchd plist contained `--config <path>` will have their plist auto-rewritten on first daemon launch (Whis B2). No manual action needed.

### Added

- New TUI Config view at sidebar position 6 (`⚙ 配置`) — see `docs/internal/plans/2026-04-26-tui-config-design.md`
- 4 sections (Movement / Scoring / Mispricing / Wallet) covering 40 user-editable knobs (territory A)
- Drift banner shows count of pending changes; Ctrl+R triggers polily restart sequence
- 3-tier validation: live (per keystroke) / save-time (full PolilyConfig) / startup (fatal screen)
- `polily config reset --all` / `polily config reset <key_path>` CLI escape hatches
- `polily/core/config_docs/*.md` per-knob documentation, parsed by `_loader.load_all()`
- New SQLite `config` table — flat dot-notation key_path → JSON value
- One-shot legacy yaml → db migration on first run (Whis B3): pre-v0.10.0 user customization auto-imported
- New family-level weight edit modal in TUI Config view: editing any `movement.weights.*` leaf now opens a family editor showing all 3-5 signal weights together with a live sum check (must equal 1.0 to save), an "auto-normalize" button to rescale, and a collapsible signal glossary. Single-leaf editing (which silently broke the algorithmic sum=1 invariant) is removed inside the weights subtree.

### Fixed

- **Scheduled analyses now fire on time regardless of user's local timezone.** `scan_logs.scheduled_at` was previously written with whatever TZ offset the agent emitted (e.g. `+08:00` for Beijing locale), and the dispatcher's overdue compare did a TEXT-byte sort — so `+08:00` strings sorted as "future" and overdue scheduled scans were never picked up. v0.10.0 normalizes `scheduled_at` to canonical UTC ISO at the write boundary, parses TZ in the dispatcher SQL, and runs a one-shot migration over existing rows. Existing users whose pending scheduled scans appeared "stuck" will see them dispatch on the next daemon tick after upgrading.
- **Dispatch now skips scans overdue by more than 30 minutes by default.** Mac sleep/wake or a long laptop close used to stack 8+ overdue rows; the daemon would fire them all in one tick and burn the user's Claude Code subscription quota. Stale rows now stay `pending` — user manually triggers if they want to catch up. Threshold is `stale_threshold_minutes=30` in `fetch_overdue_pending`; not user-configurable yet.
- **Restart-polily flow no longer corrupts the user's terminal.** Textual driver cleanup now runs before `os._exit(0)`, preventing leftover xterm mouse-tracking escapes (`\x1b[<...M` sequences) from spewing into the parent shell after exit. The TUI must use `os._exit` because `claude -p` spawns Node subprocesses that survive normal Python shutdown, but `os._exit` bypassed Textual's atexit handlers — leaving mouse modes (`?1000`/`?1002`/`?1003`/`?1006`/`?1015`) and alt-screen (`?1049`) active in the parent terminal. New `polily.tui.terminal_cleanup.cleanup_terminal` helper invokes the canonical driver path where reachable, falls back to writing DECRST sequences to stdout when no app/driver is in scope (R5-B).
- **Restart-polily no longer terminates the TUI itself.** Ctrl+R from `⚙ 配置` previously dumped the user back at the shell after a 2s grace period, forcing them to relaunch `polily` to keep working. Now only the daemon restarts; the TUI reloads its in-memory config snapshot from db in place so the drift banner resets to 0, and the user keeps their TUI session. Every territory A knob is consumed by the daemon (not the TUI process), so terminating the TUI was unnecessary friction (R5-A).

### Internal

- New `polily/core/config_store.py` module with `EPHEMERAL_FIELDS`, `TERRITORY_A_PREFIXES`, `ensure_seeded`, `load_all`, `upsert`, `reset`, `_migrate_yaml_to_db`
- New `save_knob_batch(db, updates)` public API in `polily/core/config.py` for atomic multi-key config writes (used by family weight modal); single Pydantic validate over merged config, BEGIN IMMEDIATE rollback on failure
- New `WeightFamilyEditModal` in `polily/tui/views/config_weight_modal.py`; `LeafRow` and `WeightFamilyNode` route clicks under `movement.weights.*` to it (single-leaf `ConfigEditModal` preserved elsewhere)
- `_signals_glossary` cross-reference section in `movement.md` is now consumed by the family modal (was orphan flagged by Whis R3); new `load_signals_glossary()` helper in `polily/core/config_docs/_loader.py`
- New `polily/core/config_yaml.py` for read-only yaml snapshot generation
- New `polily/core/config.py::load_config_from_db` (zero-arg, replaces 4 legacy yaml callers)
- New `polily/tui/views/config.py` with `ConfigView`, `ConfigSection`, `LeafRow`, `WeightsTree`, `MarketTypeNode`, `WeightFamilyNode`
- New `polily/tui/views/config_modals.py` with `ConfigEditModal`
- New `polily/tui/views/_config_fatal_screen.py` for startup config-error UX
- New CI gate `tests/test_config_docs_coverage.py` requires markdown docs for all 40 territory A keys
- `PRAGMA busy_timeout=5000` set explicitly on PolilyDB connection (was implicitly via Python sqlite3 default)
- New `TOPIC_HEARTBEAT` event topic (Whis SF10) for views that need timer-based refresh
- Daemon shutdown now logged distinctly from crashes — `handle_shutdown` writes `── shutting down (SIGTERM) ──` (or SIGINT) to the poll log before tearing down the scheduler, so post-mortem of `data/logs/poll-*.log` can tell kill-by-signal apart from a Python crash mid-poll. Daemon stderr still goes to /dev/null via the launchd plist (intentional), so this poll-log marker is the only visible record.
- NarrativeWriter agent prompt now passes both UTC and user-local time with explicit role labels: `next_check_at` MUST be UTC ISO (DB clock); narrative text uses local time with dual-TZ phrasing for readability.

### Removed

- `polily/core/config.py::load_config(path)` (yaml-based)
- `polily/core/config.py::deep_merge`
- `polily.cli.py::run_scheduler_daemon --config` argument
- `polily.cli.py::restart --config` and `status --config` arguments (unused)
- `config.example.yaml` and `config.minimal.yaml`

## [0.9.5] — 2026-04-26

### Removed

- **Dead config sections cleared from `PolilyConfig`.** A wholesale audit found ~15 config subsections with zero production consumers — leftover vocabulary from the v0.5-era batch-scan pipeline that didn't survive the URL-driven redesign. Removed in full: `DisciplineConfig` (8 fields), `CounterpartyConfig` (4 fields), `ScoringWeights` (5 fields, replaced by `_TYPE_WEIGHTS` constants in `polily/scan/scoring.py`), `FiltersConfig`, `HeuristicsConfig`, `CliConfig`, `ReportingConfig`, `ExecutionHintsConfig`, `PaperTradingConfig`, `MarketTypeConfig`. Trimmed in part: `MovementConfig` (`enabled`, `rolling_window_hours`, `cusum_drift`, `cusum_threshold`, `drift_cooldown_seconds`, `drift_windows`), `ApiConfig` (`provider`, `max_retries`, `backoff_seconds`, `use_cache`, `cache_dir`), `CryptoMispricingConfig` (`price_source`, `prefer_implied_vol`), `ArchivingConfig` (`enabled`), `AgentConfig` (`enabled`, `max_concurrent`, `max_candidates`), `AiConfig` (`cli_command`). The `config.example.yaml` mirror was scrubbed in lockstep — 9 top-level dead sections + 3 orphans (`onboarding`, `checklists`, `watchlist`) + matching nested fields. **Action for users:** if your local `config.yaml` references any of these keys, no action is required — Pydantic's `extra="ignore"` silently drops them, so nothing breaks at runtime; but pruning your local config keeps it readable and matches the new shape.

- **Dead modules deleted.** `polily/monitor/drift.py` (CUSUM drift detector — superseded by movement scoring in v0.7+) and `polily/scan/filters.py` (hard-filter pass — not invoked by the URL-driven pipeline) are removed along with their test files (`tests/test_drift_detector.py`, `tests/test_event_filter.py`, `tests/test_filters.py`, plus one surgical removal in `tests/test_two_pass.py`). Both modules were test-imported only; no production caller existed.

### Internal

- **Hardcoded constants migrated to `PolilyConfig`.** `_MIN_HISTORY = 5` and `_STALE_SECONDS = 600` (in `polily/daemon/poll_job.py`) moved to `MovementConfig.min_history_entries` / `MovementConfig.stale_threshold_seconds`. `DEFAULT_MAX_PROMPT_CHARS = 5000` (in `polily/agents/base.py`) moved to `AgentConfig.max_prompt_chars`. `HEARTBEAT_SECONDS = 5` (in `polily/tui/screens/main.py`) moved to a new `TuiConfig.heartbeat_seconds`. All defaults preserved exactly — zero behavior change. Sets up a future TUI Config view to surface these as user-tunable knobs without further refactoring.

- **DRY violations fixed at config consumption sites.** `polily.monitor.models.Movement.should_trigger` previously hardcoded threshold defaults that mirrored `MovementConfig` defaults — they're now keyword-only required (`*, m_threshold, q_threshold`), forcing callers to source values from `PolilyConfig` instead of accidentally falling back to method-level defaults. Same treatment for `BaseAgent.__init__(max_prompt_chars: int)`. Production callers updated to kwarg form; the "defaults shadowing config" bug class is now structurally prevented.

- **CI meta-test added: every config field must have a production consumer.** New `tests/test_config_field_consumption.py` enforces two invariants on every `PolilyConfig` leaf: (1) it has at least one production consumer (no dead fields), and (2) any low-specificity grep match must be documented in a `LOW_SPECIFICITY_VERIFIED` registry with a `file:line` consumer reference. Pre-populated with 80 `movement.weights` anchors (dict iteration in `polily/monitor/scorer.py`) and 13 parameter-based-access anchors. Future config additions that don't get wired up will fail CI; refactors that orphan a config field will fail CI. The "config knobs that do nothing" bug class is now caught at PR time.

- **Audit tooling: `scripts/audit_config_usage.py`.** One-shot tool that enumerates every `PolilyConfig` leaf and greps production usage via a 4-level cascade heuristic (`full_path → two_seg → last_seg → quoted_key`), returning `(count, sample_lines)` with each sample tagged by match level. Drove the wholesale code deletion in this Phase 0; available for future audits when adding or restructuring config sections.

- **Audit script Level 3 cascade hardened.** `scripts/audit_config_usage.py` Level 3 (`last_seg`) now skips non-identifier segments — mirrors the existing Level 4 (`quoted_key`) `isidentifier()` guard. Phase 0 Task 5 review caught: numeric leaf segments like `5`/`30`/`60` matched `0.5`/`0.30`/`0.60` float literals in production source, falsely flagging `movement.drift_windows.*.{5,30,60}` (9 leaves) ALIVE. Bug was already theoretical after drift_windows deletion (no other nested-numeric dicts in PolilyConfig), but the cascade is hardened against future config additions.

- **`Widget.recompose()` calls fixed (4 TUI sites).** Replaced sync calls to async `Widget.recompose()` with `Widget.refresh(recompose=True)` — the sync-safe equivalent that internally schedules the async recompose. Sites: `event_detail.py`, `score_result.py`, `changelog.py`, `scan_log.py`. Caught by `RuntimeWarning: coroutine 'Widget.recompose' was never awaited` in `test_event_detail_coalesces_heartbeat_fan_out`. In production this likely worked-by-accident (Textual's reactive system re-renders on next tick), but the silent coroutine drop could have caused intermittent UI staleness. Behavior is now explicit + correct.

- **Vestigial test fixture cleanup.** Phase 0 Task 10 deleted `PaperTradingConfig` from `PolilyConfig` (zero production consumers). However ~36 fixture lines across 18 test files still set `cfg.paper_trading.{default_position_size_usd, assumed_round_trip_friction_pct}` on `MagicMock()` instances — auto-passed because MagicMock auto-creates attributes, but misled future readers about what config sections existed. All 36 lines removed; tests still green at 1298 passing. (Tracked separately by chip: `MagicMock(spec=PolilyConfig)` refactor for structural fixture hardening, deferred to a future PR.)

## [0.9.4] — 2026-04-24

### Fixed

- **HTTP `User-Agent` header now tracks `polily.__version__` at runtime** instead of a hardcoded string. v0.9.0–v0.9.3 shipped with `user_agent = "polymarket-polily/0.1"` (Pydantic default) and `user_agent: "polily/0.9"` (`config.example.yaml`), so the header sent to Polymarket APIs kept announcing stale versions after every bump — the same drift class the hatch-vcs migration just fixed for `__version__`. `ApiConfig.user_agent` now uses a `default_factory` that composes `polily/<current-version>`, and `config.example.yaml` no longer pins a version literal. Regression tests in `tests/test_version.py` fail if either source reintroduces a hardcoded version.

## [0.9.3] — 2026-04-24

### Internal

- **Version string alignment** — switched from hardcoded `version = "0.9.0"` literals (which drifted behind for both v0.9.1 and v0.9.2 — the git tag and the installed-package version didn't match) to `hatch-vcs` dynamic derivation from the git tag. `pyproject.toml` now declares `dynamic = ["version"]`; `polily/__init__.py` reads `importlib.metadata.version("polily")`. No hardcoded version string remains anywhere in the source tree — the version drift bug class is now structurally impossible.
- **New CI gate: `changelog-check`** — a new job in `.github/workflows/ci.yml` runs `scripts/check_changelog.py` on every release PR (dev → master) and enforces: (1) the top CHANGELOG section is a versioned release (not `[Unreleased]`), (2) the released version has a footer link in `releases/tag/` format (not `compare/`), (3) the `[Unreleased]` footer link compares against the current top release. Catches the "forgot to rename [Unreleased]" mistake at the CI level so it can't ship. Memory-based discipline on this kept failing, so it's now enforced by a PR gate.
- **Auto-sync `master → dev` workflow now actually auto-merges.** Previously every post-release sync PR (most recently #72) got stuck in `BLOCKED` state because `GITHUB_TOKEN`-authored PRs don't trigger CI workflows (GitHub security rule against recursive workflow invocation). The required status checks stayed `Expected` forever and auto-merge never fired. Switched `.github/workflows/sync-master-to-dev.yml` to use a fine-grained PAT (`secrets.SYNC_PAT`, Contents+PRs scoped to polily only) — PAT-authored PRs are treated as real-user PRs, triggering CI and enabling auto-merge. Next release's sync PR validates end-to-end.

## [0.9.2] — 2026-04-24

### Fixed

- `BaseAgent` error propagation: when `claude -p` exits non-zero, the API failure payload (e.g. `401 Invalid authentication credentials`, `429 Rate limit exceeded`) is emitted as JSON on **stdout** while stderr stays empty. Previously `polily/agents/base.py` only read stderr, so the TUI showed `claude CLI exited with code 1:` with nothing after the colon and users had to open `data/logs/agent_debug.log` to diagnose. Now `_extract_cli_error` parses the stdout envelope first (array or object form, `is_error` + `api_error_status` + `result`) and surfaces `[API 401] <message>` in the raised `RuntimeError`; stderr remains the fallback for crashes that never produced an envelope. Contributed by @HiveYuan in #58.

## [0.9.1] — 2026-04-23

### Fixed

- **Scheduled AI analyses were silently failing for most macOS installs.** Every daemon-triggered NarrativeWriter job died ~3s after launch with `FileNotFoundError: 'claude'`, landing as `failed` rows in `scan_logs`. Manual TUI-triggered analyses were unaffected — the bug only hit the scheduler daemon.
  - **Root cause.** The launchd-spawned daemon runs under a stripped PATH (`/usr/local/bin:/usr/bin:/bin`). Any `claude` install outside that — nvm (`~/.nvm/versions/node/<ver>/bin`), Apple Silicon Homebrew (`/opt/homebrew/bin`), asdf / fnm / volta shims — was invisible to the daemon, even though `which claude` in the user's shell worked fine.
  - **Fix.** Plist now embeds the absolute path to `claude` as `EnvironmentVariables.POLILY_CLAUDE_CLI` (resolved at install time via `shutil.which` in the user's shell context). `BaseAgent` reads that env var and falls back gracefully with an actionable log message if the cached path disappears (e.g. after `nvm uninstall <old-version>`). Content-drift auto-heal (v0.9.0) is tuned to _not_ interrupt in-flight narrator jobs when only the `claude` path changed.
  - **Action required: none for most users.** Open the TUI once after upgrading — the plist regenerates itself. First-time installs pick up the new behavior automatically.
  - **How to verify.** Run `polily doctor` and check the `4. Claude CLI` section — you should see both a `你的 shell` line and a `daemon 看到` line with matching absolute paths, both marked OK.

## [0.9.0] — 2026-04-22

### BREAKING

- **Package renamed `scanner` → `polily`.** Programmatic imports must switch from `from scanner.X import ...` to `from polily.X import ...`. CLI users are unaffected.
- **Class renamed `ScanService` → `PolilyService`** (TUI service facade) — public via `polily.tui.service`.
- **Class renamed `ScannerConfig` → `PolilyConfig`** (top-level config model) — public via `polily` (module root).
- **Dead config block removed.** `ScannerSection` (the YAML `scanner:` top-level key with `output_dir`, `max_markets_to_fetch`, `include_closed_markets`, `categories_allowlist`, `categories_blocklist`, `tags_allowlist`, `tags_blocklist`, `two_pass_scan`, `orderbook_fetch_top_n`, `recommended_scan_time_utc`) has been deleted — all 10 fields were v0.5.0 batch-scan leftovers with zero runtime readers. **Action for users:** delete the `scanner:` block from your local `config.yaml` if present (Pydantic's `extra="ignore"` will silently drop it either way, so inaction is safe — but removing the dead block keeps the file clean).
- **Report disclaimer text updated** from `"Scanner output is a research prompt..."` to `"Polily output is a research prompt..."`. If you override `reporting.disclaimer` in your `config.yaml` with the old text, you should update it.

### Fixed

- `NoActiveAppError` no longer leaks into scan-history UI text when the user closes the TUI mid-analysis. `scan_logs.error` now reads `"TUI 已关闭，分析中断"` (was `"NoActiveAppError: ..."`). Pure cosmetic — the `failed` status and atomicity contracts are unchanged.
- **Launchd plist auto-heal for upgrade safety.** Pre-v0.9.0 plists hardcode `-m scanner.cli`, which breaks after the package rename and triggers silent crash-loops under `KeepAlive`. `ensure_daemon_running` now compares on-disk plist content against the freshly-generated version and forces `launchctl unload` + `load` on mismatch — so just launching the TUI once (or running any `polily scheduler` CLI command) auto-regenerates the stale plist. Zero user action needed.

### Internal

- `user_agent` product label updated from `polymarket-scanner/0.1` to `polily/0.9`.
- CI, PR template, README dev commands all repointed from `scanner/` to `polily/`.
- `CLAUDE.md` Key Files table + architecture docs synced to the new package layout.
- **`data/scheduler.pid` removed.** Daemon no longer writes a PID file; all aliveness checks (CLI `stop`/`restart`/`status`, TUI sidebar indicator, wallet reset modal, `restart_daemon`'s SIGTERM step) now query `launchctl list com.polily.scheduler` directly via the new `polily/daemon/launchctl_query.py` helper. Eliminates the stale-PID / crash-loop-race bug class where launchctl and the PID file could disagree. Users with a lingering `data/scheduler.pid` from a prior install will have it cleaned up on first daemon start.
- **Rule-based fallback vestiges dropped.** v0.8.0 killed `NarrativeWriter`'s silent fallback but left trails: `AiConfig.enabled` / `AiConfig.fallback_on_error` (zero readers), `BaseAgent.fallback_fn` parameter (zero production callers), 4 tests exercising dead infrastructure, and `README` / `CONTRIBUTING` / `CLAUDE.md` phrases claiming "falls back to rule-based mode". All swept. Contract unchanged: CLI failures raise, `scan_logs` row marked `failed`, user sees it in scan history. `ai.enabled` / `ai.fallback_on_error` keys in a user `config.yaml` silently drop via `PolilyConfig.model_config = ConfigDict(extra="ignore")` — no migration needed.

## [0.8.5] — 2026-04-22

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
- `derive_winner` now accepts `umaResolutionStatuses=["proposed"]` as terminal (was previously blocked by the strict `last == "resolved"` gate). POC data showed 98/100 recently-resolved markets stay at `["proposed"]` forever — Gamma's metadata doesn't tick to `"resolved"` for the common optimistic-flow case. Caller still gates on `closed=1` which Polymarket sets only after the UMA 2h challenge window elapses, so `["proposed"]` at that point is effectively terminal. Deferring still applies when `last == "disputed"` (active vote) or unknown states.

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

[Unreleased]: https://github.com/ShiyuCheng2018/polily/compare/v0.11.4...dev
[0.11.4]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.11.4
[0.11.3]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.11.3
[0.11.2]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.11.2
[0.11.1]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.11.1
[0.11.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.11.0
[0.10.1]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.10.1
[0.10.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.10.0
[0.9.5]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.9.5
[0.9.4]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.9.4
[0.9.3]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.9.3
[0.9.2]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.9.2
[0.9.1]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.9.1
[0.9.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.9.0
[0.8.5]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.8.5
[0.8.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.8.0
[0.7.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.7.0
[0.6.1]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.6.1
[0.6.0]: https://github.com/ShiyuCheng2018/polily/releases/tag/v0.6.0
