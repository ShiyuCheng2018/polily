"""CLI entry point for polily scanner.

v0.5.0: stripped to TUI launch + scheduler subcommand group.
Scan, paper trading, backtest, daily briefing, etc. commands will be
re-implemented against the event-first schema in Phase 2-3.
"""

from pathlib import Path

import typer

app = typer.Typer(help="Polily — Polymarket Decision Copilot", invoke_without_command=True)


@app.callback()
def main(ctx: typer.Context):
    """Polily — Polymarket Decision Copilot. Launches TUI when no subcommand given."""
    if ctx.invoked_subcommand is None:
        from scanner.tui.app import run_tui
        run_tui()


# --- Scheduler daemon commands (Phase 3 will implement fully) ---

scheduler_app = typer.Typer(help="Manage the background watch scheduler daemon")
app.add_typer(scheduler_app, name="scheduler")


@scheduler_app.command()
def start(config_path: str = typer.Option(None, "--config", "-c")):
    """Start the scheduler daemon via launchd."""
    # TODO: v0.5.0 Phase 3 — re-implement with event-first schema
    raise NotImplementedError("v0.5.0 TODO: scheduler start")


@scheduler_app.command()
def stop():
    """Stop the scheduler daemon."""
    # TODO: v0.5.0 Phase 3
    raise NotImplementedError("v0.5.0 TODO: scheduler stop")


@scheduler_app.command()
def status(config_path: str = typer.Option(None, "--config", "-c")):
    """Show scheduler daemon status and pending jobs."""
    # TODO: v0.5.0 Phase 3
    raise NotImplementedError("v0.5.0 TODO: scheduler status")


@scheduler_app.command(name="run")
def run_scheduler_daemon(config_path: str = typer.Option(None, "--config", "-c")):
    """Run the scheduler daemon (called by launchd, not user)."""
    # TODO: v0.5.0 Phase 3
    raise NotImplementedError("v0.5.0 TODO: scheduler run")


@app.command()
def reset(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete all generated data (DB, scans, logs) for a clean start."""
    targets = [
        ("data/polily.db", "Database"),
        ("data/polily.db-shm", "WAL shared memory"),
        ("data/polily.db-wal", "WAL log"),
        ("data/scheduler.pid", "Daemon PID"),
        ("data/scheduler.log", "Daemon log"),
        ("data/agent_debug.log", "Agent debug log"),
    ]
    scan_dir = Path("data/scans")

    if not confirm:
        from rich.console import Console
        console = Console()
        console.print("[yellow]Will delete the following data:[/yellow]")
        for path, label in targets:
            exists = "Y" if Path(path).exists() else "-"
            console.print(f"  {exists} {path} ({label})")
        scan_count = len(list(scan_dir.glob("*.json"))) if scan_dir.exists() else 0
        console.print(f"  {'Y' if scan_count else '-'} data/scans/*.json ({scan_count} scan archives)")
        console.print()
        if not typer.confirm("Confirm delete all data?"):
            console.print("[dim]Cancelled[/dim]")
            return

    # Stop daemon first
    import subprocess
    subprocess.run(
        ["launchctl", "unload", str(Path.home() / "Library/LaunchAgents/com.polily.scheduler.plist")],
        capture_output=True, check=False,
    )

    deleted = 0
    for path, _label in targets:
        p = Path(path)
        if p.exists():
            p.unlink()
            deleted += 1

    # Clear scan archives
    if scan_dir.exists():
        for f in scan_dir.glob("*.json"):
            f.unlink()
            deleted += 1

    from rich.console import Console
    Console().print(f"[green]Deleted {deleted} files. Database will be recreated on next launch.[/green]")


if __name__ == "__main__":
    app()
