"""CLI entry point for Polily.

v0.5.0: minimal CLI — TUI launch + scheduler subcommand group.
"""

from pathlib import Path

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


@app.callback()
def main(ctx: typer.Context):
    """Polily — A Polymarket Monitoring Agent That Actually Works. Launches TUI when no subcommand given."""
    if ctx.invoked_subcommand is None:
        from polily.tui.app import run_tui
        from polily.tui.service import PolilyService
        service = PolilyService()
        _regenerate_yaml_snapshot(service.config)
        run_tui(service=service)


# --- Scheduler daemon commands ---

scheduler_app = typer.Typer(help="Manage the background scheduler daemon")
app.add_typer(scheduler_app, name="scheduler")

# Path kept for Task C one-shot stale-file cleanup on daemon startup
# and for the `reset` command's legacy-file deletion table. No read
# logic in this module relies on it — launchctl is authoritative.
PID_FILE = Path("data/scheduler.pid")


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
        typer.echo("Scheduler is not running (no PID file).")
        # Still attempt unload so any registered launchctl entry gets cleared.
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        raise typer.Exit(1)

    if not _pid_alive(pid):
        typer.echo(f"Scheduler PID {pid} is not running. Cleaning up stale PID file.")
        PID_FILE.unlink(missing_ok=True)
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
        typer.echo("Scheduler: NOT RUNNING (no PID file)")
        raise typer.Exit(0)

    alive = _pid_alive(pid)
    if not alive:
        typer.echo(f"Scheduler: NOT RUNNING (stale PID {pid})")
        PID_FILE.unlink(missing_ok=True)
        raise typer.Exit(0)

    typer.echo(f"Scheduler: RUNNING (PID {pid})")


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
        return load_config_from_db(db)
    finally:
        db.close()


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
        db = PolilyDB(cfg.archiving.db_file)
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
