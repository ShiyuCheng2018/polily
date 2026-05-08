## 5. File Paths

Polily's data directory is OS-standard:

- **macOS**: `~/Library/Application Support/polily/`
- **Linux**: `$XDG_DATA_HOME/polily` or `~/.local/share/polily/`

Inside the data dir:
- `polily.db` — primary SQLite database (all schema in §3 lives here)
- `logs/` — daemon stdout/stderr logs and scheduler logs
- `config.yaml` — read-only snapshot of the `config` table (regenerated on every save, never hand-edited)

Override the data dir with the `POLILY_DATA_DIR` env var or `polily --data-dir=PATH` CLI flag.

Use the per-call input `official_strategy_path` (see §7) to locate the packaged default strategy when you need to fall back. Do not hard-code package paths — they vary by install method (pipx vs pip vs editable install).
