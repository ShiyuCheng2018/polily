"""CLI entry point for Polily.

v0.5.0: minimal CLI — TUI launch + scheduler subcommand group.
"""

from pathlib import Path

import typer

app = typer.Typer(help="Polily — A Polymarket Monitoring Agent That Actually Works", invoke_without_command=True)


@app.callback()
def main(ctx: typer.Context):
    """Polily — A Polymarket Monitoring Agent That Actually Works. Launches TUI when no subcommand given."""
    if ctx.invoked_subcommand is None:
        from polily.tui.app import run_tui
        run_tui()


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
def run_scheduler_daemon(config_path: str = typer.Option(None, "--config", "-c")):
    """Run the scheduler daemon in the foreground (called by launchd, not user)."""
    from polily.core.config import PolilyConfig, load_config
    from polily.core.db import PolilyDB
    from polily.daemon.scheduler import run_daemon

    if config_path:
        config = load_config(Path(config_path))
    else:
        config = PolilyConfig()

    db_file = config.archiving.db_file
    db = PolilyDB(db_file)
    try:
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
def restart(config_path: str = typer.Option(None, "--config", "-c")):
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
def status(config_path: str = typer.Option(None, "--config", "-c")):
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
    """Layered config load used by reset paths. Isolated so tests can stub it."""
    from polily.core.config import PolilyConfig, load_config
    minimal = Path("config.minimal.yaml")
    example = Path("config.example.yaml")
    if minimal.exists() and example.exists():
        return load_config(minimal, defaults_path=example)
    if example.exists():
        return load_config(example)
    return PolilyConfig()


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
        ("data/scheduler.pid", "Daemon PID"),
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
