<!-- external-only -->
## 9. Codebase Pointers

The most common entry points when reading / modifying polily:

### Core flow

- **`polily/cli.py`** — CLI surface (`polily`, `polily scheduler run`, `polily reset`, `polily config ...`). Read this first to understand how polily processes start.
- **`polily/scan/pipeline.py::fetch_and_score_event`** — single-event flow from pasted URL → Gamma API fetch → enrichment (orderbook, prices, fees, mispricing) → scoring → tier assignment → persistence. The orchestrator.
- **`polily/scan/scoring.py::compute_structure_score`** — per-market 5-dimension structure score (liquidity / verifiability / probability / time / friction). `_TYPE_WEIGHTS` constants define market_type-specific dimension weights.
- **`polily/scan/event_scoring.py::compute_event_quality_score`** — event-level 6-dimension score (information-value / liquidity-aggregate / resolution-quality / consistency / time-window / best-market-quality). NOT an aggregate of child markets.

### Daemon

- **`polily/daemon/scheduler.py`** — APScheduler daemon entry. Dual-executor setup (poll: 1 thread, ai: 5 threads). Owns launchctl plist management.
- **`polily/daemon/poll_job.py::global_poll`** — every-30s tick. Fetches prices, runs resolution pass, refreshes scores, dispatches overdue pending analyses (Step 3.5), runs intelligence layer (movement scoring + trigger).
- **`polily/daemon/score_refresh.py::refresh_scores`** — recomputes price-sensitive dimensions per tick for monitored markets.
- **`polily/daemon/event_metadata_regen.py`** — honors Polymarket's `context_requires_regen` flag with cooldown (v0.12.0+).

### Agent

- **`polily/agents/narrative_writer.py::NarrativeWriterAgent`** — the AI agent. `_build_prompt` assembles the 4-part prompt (per-call YAML + manual.md + active strategy + protocol footer). Output parsing via `polily/agents/frontmatter.py::split_frontmatter` (v0.12.0 markdown mode).
- **`polily/agents/base.py::BaseAgent`** — claude CLI wrapper. Handles retry, JSON parsing, prompt overflow → temp-file fallback (`max_prompt_chars` knob).
- **`polily/agents/skill_sources/core/*.md`** — single source of truth for the manual and the marketplace plugin SKILL.md (see `scripts/generate_skills.py`).

### TUI

- **`polily/tui/app.py::PolilyApp`** — Textual app entry. F2 language toggle, i18n init, theme registration.
- **`polily/tui/screens/main.py`** — sidebar + content layout, 5s heartbeat bus.
- **`polily/tui/service.py::PolilyService`** — backend bridge for TUI views. Owns `wallet` / `positions` / `trade_engine`. `analyze_event` is the manual-trigger AI dispatch entry.
- **`polily/tui/views/`** — per-pane views (tasks / monitor / paper / wallet / history / strategy / etc.).

### Storage / config

- **`polily/core/db.py::PolilyDB`** — SQLite handle. `_init_schema` runs DDL on every open (idempotent ALTER patterns for upgrades).
- **`polily/core/config.py::load_config_from_db`** — canonical config bootstrap. Drives `_migrate_yaml_to_db` + `ensure_seeded` + v0.12.0 hotfix migrations under `BEGIN IMMEDIATE`.
- **`polily/core/config_store.py`** — flat `key_path` ↔ JSON store backing `PolilyConfig`. `upsert` validates against Pydantic before insert.
- **`polily/core/paths.py`** — three-layer path resolution (CLI flag > env > platformdirs default).

### Tests

- **TDD is the standard.** Every behavior change has a corresponding test. Run via `.venv/bin/python -m pytest -q`.
- Test files mirror module paths under `tests/` (no `tests/unit/` vs `tests/integration/` split — flat layout).
- Migration tests live in `tests/test_db_migration_*.py`, packaging tests in `tests/test_*_packaging.py`.

### Development conventions

Read **`CLAUDE.md`** in the repo root for the authoritative development guide — release process, branch channel discipline (dev is the only channel to master, release PRs use merge-commits not squash), common pitfalls (CLOB API quirks, paper-trading invariants), and the TDD workflow.
<!-- /external-only -->
