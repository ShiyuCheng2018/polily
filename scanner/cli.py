"""CLI entry point for polily scanner.

v0.5.0: minimal CLI — TUI launch + scheduler subcommand group.
"""

import os
import signal
from pathlib import Path

import typer

app = typer.Typer(help="Polily — Polymarket Decision Copilot", invoke_without_command=True)


@app.callback()
def main(ctx: typer.Context):
    """Polily — Polymarket Decision Copilot. Launches TUI when no subcommand given."""
    if ctx.invoked_subcommand is None:
        from scanner.tui.app import run_tui
        run_tui()


# --- Scheduler daemon commands ---

scheduler_app = typer.Typer(help="Manage the background scheduler daemon")
app.add_typer(scheduler_app, name="scheduler")

PID_FILE = Path("data/scheduler.pid")


def _read_pid() -> int | None:
    """Read PID from file. Returns None if missing or invalid."""
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def _pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@scheduler_app.command(name="run")
def run_scheduler_daemon(config_path: str = typer.Option(None, "--config", "-c")):
    """Run the scheduler daemon in the foreground (called by launchd, not user)."""
    from scanner.core.config import ScannerConfig, load_config
    from scanner.core.db import PolilyDB
    from scanner.daemon.scheduler import run_daemon

    if config_path:
        config = load_config(Path(config_path))
    else:
        config = ScannerConfig()

    db_file = config.archiving.db_file
    db = PolilyDB(db_file)
    try:
        run_daemon(db, config=config)
    finally:
        db.close()


@scheduler_app.command()
def stop():
    """Stop the scheduler daemon by sending SIGTERM."""
    pid = _read_pid()
    if pid is None:
        typer.echo("Scheduler is not running (no PID file).")
        raise typer.Exit(1)

    if not _pid_alive(pid):
        typer.echo(f"Scheduler PID {pid} is not running. Cleaning up stale PID file.")
        PID_FILE.unlink(missing_ok=True)
        raise typer.Exit(1)

    os.kill(pid, signal.SIGTERM)
    typer.echo(f"Sent SIGTERM to scheduler (PID {pid}).")


@scheduler_app.command()
def restart(config_path: str = typer.Option(None, "--config", "-c")):
    """Restart the scheduler daemon (stop + start via launchd)."""
    pid = _read_pid()
    if pid is not None and _pid_alive(pid):
        os.kill(pid, signal.SIGTERM)
        typer.echo(f"Stopped scheduler (PID {pid}).")
        # Brief wait for cleanup
        import time
        time.sleep(1)

    from scanner.daemon.scheduler import ensure_daemon_running

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
    from scanner.core.config import ScannerConfig, load_config
    minimal = Path("config.minimal.yaml")
    example = Path("config.example.yaml")
    if minimal.exists() and example.exists():
        return load_config(minimal, defaults_path=example)
    if example.exists():
        return load_config(example)
    return ScannerConfig()


def _stop_daemon_if_running() -> None:
    import time
    pid = _read_pid()
    if pid is not None and _pid_alive(pid):
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)


@app.command()
def reset(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    wallet_only: bool = typer.Option(
        False, "--wallet-only",
        help="仅重置钱包 (保留 events/markets/analyses)。下次启动 auto-migration 会按 config 的 starting_balance 重新开始。",
    ),
):
    """Delete all generated data (DB, logs) for a clean start.

    Use --wallet-only to reset only the wallet-side state (positions, wallet,
    wallet_transactions, open paper_trades) while keeping events, markets, and
    analysis history.
    """
    from rich.console import Console
    console = Console()

    if wallet_only:
        from scanner.core.db import PolilyDB
        from scanner.core.wallet_reset import reset_wallet

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
        ("data/poll.log", "Poll log"),
        ("data/agent_debug.log", "Agent debug log"),
    ]

    if not confirm:
        console.print("[yellow]Will delete the following data:[/yellow]")
        for path, label in targets:
            exists = "Y" if Path(path).exists() else "-"
            console.print(f"  {exists} {path} ({label})")
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

    console.print(f"[green]Deleted {deleted} files. Database will be recreated on next launch.[/green]")


if __name__ == "__main__":
    app()
