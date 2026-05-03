"""CLI entry point for Polily.

v0.5.0: minimal CLI — TUI launch + scheduler subcommand group.
"""

import sys
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Polily — A Polymarket Monitoring Agent That Actually Works", invoke_without_command=True)


def _regenerate_yaml_snapshot(config) -> None:
    """Overwrite config.yaml with a fresh snapshot from the loaded PolilyConfig.

    Best-effort: log + continue if disk is read-only or parent dir missing.
    yaml is a debug snapshot, not load-bearing — runtime works without it.
    """
    from polily.core.config_yaml import generate_yaml
    target = Path("config.yaml")
    try:
        generate_yaml(config, target)
    except OSError as e:
        import logging
        logging.getLogger(__name__).warning(
            "Could not regenerate %s: %s", target, e
        )


def _emit_migration_status_to_stderr(status=None) -> None:
    """Surface yaml→db migration status to the user (SF1 / AC2).

    Called by CLI bootstrap paths after `load_config_from_db`. Without
    this, the v0.9.x → v0.10.0 upgrade had a silent failure mode where
    a user with an out-of-range value in `config.yaml` would have it
    quietly clobbered by the next yaml regen — they lost customizations
    with zero feedback.

    `status` defaults to `get_last_migration_status()` (whatever the
    most recent migration in this process produced). Tests pass an
    explicit status to exercise each branch.

    Status cases:
      - ("ok", N)                       — visible: "已迁移 N 项..."
      - ("skipped_invalid", reason)     — visible: warn + .bak hint
      - ("skipped_no_yaml",)            — silent (fresh install / new user)
      - ("skipped_already_migrated",)   — silent (every startup after first)
      - None                            — silent (no migration happened)
    """
    if status is None:
        from polily.core.config_store import get_last_migration_status
        status = get_last_migration_status()
    if status is None:
        return

    kind = status[0]
    if kind == "ok":
        n = status[1]
        sys.stderr.write(
            f"✅ 已迁移 {n} 项旧版配置 (config.yaml → polily.db)。"
            "可在 ⚙ 配置 中调整。\n"
        )
    elif kind == "skipped_invalid":
        reason = status[1] if len(status) > 1 else ""
        # Truncate long Pydantic ValidationError dumps so the warning stays
        # legible; full reason is in the log.
        short_reason = reason.split("\n", 1)[0][:120] if reason else ""
        sys.stderr.write(
            f"⚠ 旧版 config.yaml 校验失败 ({short_reason})；已使用默认值。"
            "原文件已保留为 config.yaml.bak — 可手动迁移或删除。\n"
        )
    # "skipped_no_yaml" and "skipped_already_migrated" → silent


@app.callback()
def main(
    ctx: typer.Context,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="Override polily data directory (default: ~/Library/Application Support/polily on macOS, $XDG_DATA_HOME/polily on Linux). Useful for ad-hoc testing or per-environment isolation.",
        ),
    ] = None,
    log_dir: Annotated[
        Path | None,
        typer.Option(
            "--log-dir",
            help="Override polily log directory (default: <data-dir>/logs).",
        ),
    ] = None,
):
    """Polily — A Polymarket Monitoring Agent That Actually Works. Launches TUI when no subcommand given."""
    from polily.core import paths
    if data_dir is not None:
        paths.set_data_dir_override(data_dir)
    if log_dir is not None:
        paths.set_log_dir_override(log_dir)

    if ctx.invoked_subcommand is None:
        from polily.tui.app import run_tui
        from polily.tui.service import PolilyService
        service = PolilyService()
        # SF1 / AC2 — surface yaml→db migration status BEFORE entering the
        # Textual TUI (which takes over the terminal). Critical for the
        # invalid-yaml case where the user's customizations are .bak'd.
        _emit_migration_status_to_stderr()
        _regenerate_yaml_snapshot(service.config)
        run_tui(service=service)


# --- Scheduler daemon commands ---

scheduler_app = typer.Typer(help="Manage the background scheduler daemon")
app.add_typer(scheduler_app, name="scheduler")

# v0.9.0: launchctl is the single source of truth for daemon aliveness
# (see `polily/daemon/launchctl_query.py`). Polily no longer writes
# `data/scheduler.pid`; the legacy file is one-shot swept on daemon
# startup via `polily/daemon/scheduler.py::_sweep_legacy_pid_file`.
# Nothing in this module reads or writes a PID file anymore — copy
# below MUST NOT mention one.


def _read_pid() -> int | None:
    """Return the daemon PID via launchctl, or None if not running.

    v0.9.0: previously read `data/scheduler.pid`. Switched to launchctl
    so the daemon's real registration state is the single source of
    truth — eliminates stale-PID false positives after SIGKILL and
    crash-loop-restart races.
    """
    from polily.daemon.launchctl_query import get_daemon_pid
    return get_daemon_pid()


def _pid_alive(pid: int) -> bool:
    """Check whether `pid` is still the live daemon PID.

    v0.9.0 semantic change: previously `os.kill(pid, 0)` returned True
    for ANY process with that PID (including a PID recycled after
    SIGKILL). Now we re-query launchctl and return True only if the
    current daemon PID equals the argument. Narrow race window: if
    launchctl's KeepAlive respawns the daemon between `_read_pid()`
    and `_pid_alive(pid)`, this returns False — callers that care
    must re-read, not cache.
    """
    from polily.daemon.launchctl_query import get_daemon_pid
    current = get_daemon_pid()
    return current == pid


@scheduler_app.command(name="run")
def run_scheduler_daemon():
    """Run the scheduler daemon in the foreground (called by launchd, not user).

    v0.10.0 BREAKING: --config flag removed. db.config is the only
    config source; use TUI → ⚙ 配置 or `polily config reset` to manage.
    """
    from polily.core.config import (
        ConfigValidationError,
        default_db_path,
        load_config_from_db,
    )
    from polily.core.db import PolilyDB
    from polily.daemon.scheduler import run_daemon

    db = PolilyDB(default_db_path())
    try:
        try:
            config = load_config_from_db(db)
        except ConfigValidationError as e:
            # Per design §7.3 — daemon validate-fail exits 1 (no fallback).
            # User repairs via TUI fatal screen or `polily config reset`.
            typer.echo(f"FATAL: db.config has invalid values: {e}", err=True)
            raise typer.Exit(1) from e
        # SF1 / AC2 — daemon's stderr goes to its launchd log; the user
        # won't see it unless they tail the log, but it's still better
        # than silent. TUI bootstrap is the primary visibility path.
        _emit_migration_status_to_stderr()
        # Regenerate yaml snapshot so disk reflects daemon's runtime state.
        # Per design §4.4 — both TUI and daemon are yaml regen hooks.
        _regenerate_yaml_snapshot(config)
        run_daemon(db, config=config)
    finally:
        db.close()


@scheduler_app.command()
def stop():
    """Stop the scheduler daemon (SIGTERM + launchctl unload).

    `launchctl unload` is required because the plist has `KeepAlive=true`
    on non-zero exit — SIGTERM causes a non-zero exit, so without unload
    launchctl would relaunch the daemon against the (possibly stale, e.g.
    pre-v0.9.0) plist and enter a crash loop.
    """
    import subprocess

    from polily.daemon.scheduler import PLIST_PATH

    pid = _read_pid()
    if pid is None:
        typer.echo("Scheduler is not running (launchctl: not loaded).")
        # Still attempt unload so any registered launchctl entry gets cleared.
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        raise typer.Exit(1)

    if not _pid_alive(pid):
        typer.echo(
            f"Scheduler PID {pid} is not running. "
            "Stale launchctl entry — will be replaced on next start."
        )
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        raise typer.Exit(1)

    from polily.daemon.launchctl_query import kill_daemon
    kill_daemon("TERM")
    typer.echo(f"Sent SIGTERM to scheduler (PID {pid}).")
    # Unload the launchctl registration so KeepAlive can't respawn it.
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    typer.echo("Unloaded launchctl registration.")


@scheduler_app.command()
def restart():
    """Restart the scheduler daemon (stop + start via launchd)."""
    pid = _read_pid()
    if pid is not None and _pid_alive(pid):
        from polily.daemon.launchctl_query import kill_daemon
        kill_daemon("TERM")
        typer.echo(f"Stopped scheduler (PID {pid}).")
        # Brief wait for cleanup
        import time
        time.sleep(1)

    from polily.daemon.scheduler import ensure_daemon_running

    started = ensure_daemon_running()
    if started:
        typer.echo("Scheduler restarted via launchd.")
    else:
        typer.echo("Scheduler is already running.")


@scheduler_app.command()
def status():
    """Show scheduler daemon status and pending jobs."""
    pid = _read_pid()
    if pid is None:
        typer.echo("Scheduler: NOT RUNNING (launchctl: not loaded)")
        raise typer.Exit(0)

    alive = _pid_alive(pid)
    if not alive:
        typer.echo(f"Scheduler: NOT RUNNING (stale launchctl PID {pid})")
        raise typer.Exit(0)

    typer.echo(f"Scheduler: RUNNING (PID {pid})")


# --- Config escape-hatch command ---

config_app = typer.Typer(help="Manage polily configuration")
app.add_typer(config_app, name="config")


@config_app.command(name="reset")
def cmd_config_reset(
    key_path: str = typer.Argument(
        None,
        help="key_path to reset (e.g., movement.magnitude_threshold). Omit if using --all.",
    ),
    all: bool = typer.Option(  # noqa: A002 — `--all` is the standard CLI flag name
        False, "--all",
        help="Reset ALL config values to Pydantic defaults (clears db.config).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip confirmation prompt for --all.",
    ),
):
    """Reset config to Pydantic defaults.

    Use cases:
      - polily config reset --all          # full reset (after fatal screen)
      - polily config reset movement.magnitude_threshold  # single key

    Whis SF11 — archiving.db_file is bootstrapped from Pydantic default
    (same pattern as `_load_user_config` and `run_scheduler_daemon`). Its
    db.config row is informational; the actual db path is install-time.
    """
    from polily.core.config import PolilyConfig, default_db_path
    from polily.core.config_store import (
        EPHEMERAL_FIELDS,
        ConfigSaveError,
        _flatten_pydantic,
    )
    from polily.core.config_store import (
        reset as reset_key,
    )
    from polily.core.db import PolilyDB

    db = PolilyDB(default_db_path())
    try:
        if all:
            if not yes and not typer.confirm(
                "重置 ALL config 为默认 (db.config 清空重新 seed)？此操作不可撤销。"
            ):
                typer.echo("Cancelled")
                raise typer.Exit(0)
            # SF3 (v0.10.0) — wrap DELETE + ensure_seeded in BEGIN IMMEDIATE
            # so a concurrent daemon poll tick can never observe an empty
            # config table mid-reset. Same pattern as load_config_from_db.
            #
            # Re-import ensure_seeded from the source module rather than
            # using the local binding so monkeypatch.setattr(config_store,
            # "ensure_seeded", ...) in tests sees the override.
            from polily.core import config_store
            db.conn.execute("BEGIN IMMEDIATE")
            try:
                db.conn.execute("DELETE FROM config")
                config_store.ensure_seeded(db)
                db.conn.commit()
            except Exception:
                db.conn.rollback()
                raise
            # SF3 — daemon's in-memory PolilyConfig snapshot still has the
            # pre-reset values. Tell the user to restart so they aren't
            # confused about why their reset "didn't take effect" until
            # next launchd respawn.
            typer.echo(
                "✅ 已重置全部 config 为默认值。\n"
                "若 daemon 正在运行，请执行 'polily scheduler restart' "
                "让新值生效。"
            )
            return

        if key_path is None:
            typer.echo(
                "Either provide a key_path or pass --all. "
                "See `polily config reset --help`.",
                err=True,
            )
            raise typer.Exit(2)

        if key_path in EPHEMERAL_FIELDS:
            typer.echo(
                f"{key_path} is a runtime-computed field, "
                "no persisted value to reset.",
                err=True,
            )
            raise typer.Exit(2)

        defaults_flat = _flatten_pydantic(PolilyConfig())
        if key_path not in defaults_flat:
            typer.echo(f"Unknown key_path: {key_path}", err=True)
            raise typer.Exit(2)

        try:
            reset_key(db, key_path)
        except ConfigSaveError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(2) from e
        typer.echo(f"✅ 已重置 {key_path} = {defaults_flat[key_path]}")
    finally:
        db.close()


def _load_user_config():
    """Load PolilyConfig from db.config (used by `polily reset` paths).

    Per SF11 — archiving.db_file is HIDDEN_IN_TUI, so we bootstrap
    the db path via default_db_path() instead of trying to read it
    from the very db.config we haven't loaded yet. See default_db_path
    docstring for the chicken-and-egg rationale.
    """
    from polily.core.config import default_db_path, load_config_from_db
    from polily.core.db import PolilyDB

    db = PolilyDB(default_db_path())
    try:
        config = load_config_from_db(db)
    finally:
        db.close()
    # SF1 / AC2 — emit migration status to stderr after load, so the user
    # sees the upgrade banner even on `polily reset` paths.
    _emit_migration_status_to_stderr()
    return config


def _stop_daemon_if_running() -> None:
    import time
    pid = _read_pid()
    if pid is not None and _pid_alive(pid):
        from polily.daemon.launchctl_query import kill_daemon
        kill_daemon("TERM")
        time.sleep(1)


@app.command()
def reset(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    wallet_only: bool = typer.Option(
        False, "--wallet-only",
        help="仅重置钱包 (保留 events/markets/analyses)。钱包按 config 的 starting_balance 重新开始。",
    ),
):
    """Delete all generated data (DB, logs) for a clean start.

    Use --wallet-only to reset only the wallet-side state (positions, wallet,
    wallet_transactions) while keeping events, markets, and analysis history.
    """
    from rich.console import Console
    console = Console()

    if wallet_only:
        from polily.core.db import PolilyDB
        from polily.core.wallet_reset import reset_wallet

        cfg = _load_user_config()
        target_balance = cfg.wallet.starting_balance

        if not confirm and not typer.confirm(
            f"Reset wallet to ${target_balance}? (events/markets preserved)"
        ):
            console.print("[dim]Cancelled[/dim]")
            return

        _stop_daemon_if_running()
        from polily.core.config import default_db_path
        db = PolilyDB(default_db_path())
        try:
            reset_wallet(db, starting_balance=target_balance)
        finally:
            db.close()
        console.print(
            f"[green]Wallet reset to ${target_balance}. "
            f"Events / markets / analyses preserved.[/green]"
        )
        return

    targets = [
        ("data/polily.db", "Database"),
        ("data/polily.db-shm", "WAL shared memory"),
        ("data/polily.db-wal", "WAL log"),
        ("data/poll.log", "Poll log (legacy path, pre-0.6.0)"),
        ("data/agent_debug.log", "Agent debug log"),
    ]
    # Also clear rotated per-restart poll logs under data/logs/.
    log_dir = Path("data/logs")
    rotated_poll_logs = (
        sorted(log_dir.glob("poll-v*.log")) if log_dir.exists() else []
    )

    if not confirm:
        console.print("[yellow]Will delete the following data:[/yellow]")
        for path, label in targets:
            exists = "Y" if Path(path).exists() else "-"
            console.print(f"  {exists} {path} ({label})")
        if rotated_poll_logs:
            console.print(
                f"  Y data/logs/poll-v*.log ({len(rotated_poll_logs)} rotated "
                "poll logs)"
            )
        console.print()
        console.print("[dim]💡 只想重置钱包？改用 polily reset --wallet-only[/dim]")
        if not typer.confirm("Confirm delete all data?"):
            console.print("[dim]Cancelled[/dim]")
            return

    _stop_daemon_if_running()

    deleted = 0
    for path, _label in targets:
        p = Path(path)
        if p.exists():
            p.unlink()
            deleted += 1
    for p in rotated_poll_logs:
        if p.exists():
            p.unlink()
            deleted += 1

    console.print(f"[green]Deleted {deleted} files. Database will be recreated on next launch.[/green]")


@app.command()
def doctor():
    """运行环境诊断。检查 Nerd Font、终端尺寸、数据库、Claude CLI。"""
    from polily.doctor import run_doctor
    run_doctor()


if __name__ == "__main__":
    app()
