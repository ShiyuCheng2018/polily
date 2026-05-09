## 5. File Paths

The canonical path resolver is `polily/core/paths.py`. Three-layer resolution (highest priority first):

1. **CLI flag** — `polily --data-dir=PATH` sets a process-scoped override
2. **Env vars** — `POLILY_DATA_DIR` (data root) and `POLILY_LOG_DIR` (logs only — escape hatch when you want logs elsewhere)
3. **Default** — `platformdirs.user_data_dir("polily")`:
   - **macOS**: `~/Library/Application Support/polily/`
   - **Linux**: `$XDG_DATA_HOME/polily` or `~/.local/share/polily/`

If `POLILY_LOG_DIR` is unset, `log_dir()` defaults to `data_dir() / "logs"` — so a single `POLILY_DATA_DIR` covers both.

### Inside `data_dir()`

| Path | Purpose |
|---|---|
| `polily.db` | Primary SQLite database — every table in §3 lives here |
| `config.yaml` | **Read-only** snapshot of the `config` table, regenerated on every polily startup. Manual edits are silently overwritten — the canonical source is the `config` table (§3). Pre-v0.11.0 had a writable yaml at `$CWD/config.yaml` — that path is **legacy** and only used during one-time migration |
| `logs/` | Daemon + agent log files (see below) |

### Inside `log_dir()` (default `data_dir() / logs/`)

| File | Producer | Use |
|---|---|---|
| `agent_feedback.log` | `narrative_writer._write_dev_feedback` | Append-only log of agent `dev_feedback` strings (one line per successful analysis). Polily maintainers grep this to harvest agent-side issue reports |
| `agent_debug.log` | `BaseAgent` (claude CLI wrapper) | stdout/stderr dump from claude CLI subprocess, captured on retry / parse failures |
| `daemon-stderr.log`, `daemon-stdout.log` | launchd / `polily scheduler run` | Daemon process output — covers poll cycles, score refresh, scan dispatches |
| `scheduler-stderr.log`, `scheduler-stdout.log` | APScheduler internal | Scheduler-level diagnostics (job dispatch, missed runs) |

### `official_strategy_path` (per-call, not under data_dir)

The packaged official strategy — `polily/strategies/default.md` inside the polily Python package — has a different absolute path per install method (pipx vs pip vs editable install). **Do not hard-code it.** Use the `official_strategy_path` field injected in §7's per-call YAML; it's resolved from `polily.__file__` at dispatch time and works for every install topology.

### Quick reference

To find the active install's data dir from the shell (when troubleshooting):

    .venv/bin/python -c "from polily.core.paths import data_dir, log_dir, db_path; print(data_dir()); print(log_dir()); print(db_path())"

If you need to query polily.db directly via `Bash`, use `db_path()` from `polily.core.paths` — never hard-code `~/Library/...` or `~/.local/share/...` because the user may have set `POLILY_DATA_DIR` or `--data-dir`.
