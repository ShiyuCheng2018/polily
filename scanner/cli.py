"""CLI entry point for polily scanner."""

import asyncio
import json
from datetime import UTC
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from scanner.api import PolymarketClient, parse_gamma_event
from scanner.archive import (
    find_entry_by_rank,
    find_entry_in_archive,
    save_scan_unified,
)
from scanner.config import ScannerConfig, load_config
from scanner.pipeline import run_scan_pipeline
from scanner.render import (
    console,
    render_backtest_tables,
    render_daily_deltas,
    render_dashboard,
    render_tier_a,
)

app = typer.Typer(help="Polily — Polymarket Decision Copilot", invoke_without_command=True)


@app.callback()
def main(ctx: typer.Context):
    """Polily — Polymarket Decision Copilot. Launches TUI when no subcommand given."""
    if ctx.invoked_subcommand is None:
        from scanner.tui.app import run_tui
        run_tui()


def _open_db(config: ScannerConfig):
    """Open the unified PolilyDB."""
    from scanner.db import PolilyDB
    return PolilyDB(config.archiving.db_file)


def _open_paper_db(config: ScannerConfig):
    """Open PaperTradingDB backed by PolilyDB."""
    from scanner.paper_trading import PaperTradingDB
    return PaperTradingDB(
        _open_db(config),
        position_size_usd=config.paper_trading.default_position_size_usd,
        friction_pct=config.paper_trading.assumed_round_trip_friction_pct,
    )


def _resolve_config(config_path: str | None) -> ScannerConfig:
    if config_path:
        p = Path(config_path)
        if p.name == "config.minimal.yaml":
            return load_config(p, defaults_path=Path("config.example.yaml"))
        return load_config(p)
    minimal = Path("config.minimal.yaml")
    example = Path("config.example.yaml")
    if minimal.exists() and example.exists():
        return load_config(minimal, defaults_path=example)
    if example.exists():
        return load_config(example)
    return ScannerConfig()


# --- Commands ---


@app.command()
def scan(
    config_path: str = typer.Option(None, "--config", "-c", help="Path to config YAML"),
    brief: bool = typer.Option(False, "--brief", help="Dashboard only"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Full deep dive on Tier A"),
    simple: bool = typer.Option(False, "--simple", help="Newbie-friendly output (fewer fields, inline explanations)"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Disable all AI agents (pure rule-based mode)"),
    lean: bool = typer.Option(False, "--lean", help="Show conditional direction advice (off by default)"),
    category: str = typer.Option(None, "--category", help="Filter by market type"),
):
    """Scan Polymarket for candidate markets."""
    config = _resolve_config(config_path)

    # First-run onboarding
    from scanner.onboarding import WELCOME_TEXT, mark_onboarding_done, should_show_onboarding
    marker = Path("data/.onboarding_done")
    if should_show_onboarding(marker):
        console.print(Panel(WELCOME_TEXT, border_style="cyan", title="First Run"))
        mark_onboarding_done(marker)

    markets = asyncio.run(_fetch_markets(config))

    if not markets:
        console.print("[red]No markets fetched. Check your connection.[/red]")
        raise typer.Exit(1)

    if no_ai:
        config.ai.enabled = False
    if lean:
        config.execution_hints.show_conditional_advice = True

    total_scanned = len(markets)
    tiers = run_scan_pipeline(markets, config)

    if category:
        tiers.tier_a = [c for c in tiers.tier_a if c.market.market_type == category]
        tiers.tier_b = [c for c in tiers.tier_b if c.market.market_type == category]

    render_dashboard(tiers, config, total_scanned=total_scanned)
    if not brief:
        if simple:
            _render_simple_mode(tiers, config)
        else:
            show_lean = config.execution_hints.show_conditional_advice
            render_tier_a(tiers, verbose=verbose, show_lean=show_lean)

    if config.archiving.enabled:
        scan_id = save_scan_unified(tiers, config.archiving.archive_dir)
        console.print(f"\n [dim]归档: data/scans/{scan_id}.json[/dim]")


@app.command()
def daily(
    config_path: str = typer.Option(None, "--config", "-c", help="Path to config YAML"),
):
    """Daily briefing: today's scan + yesterday's tracking + paper trade updates."""
    config = _resolve_config(config_path)

    # Section 1: Today's scan
    scan(config_path=config_path, brief=False, verbose=False, simple=False,
         no_ai=False, lean=False, category=None)

    # Section 2: Yesterday tracking
    from scanner.daily_briefing import generate_briefing

    briefing = generate_briefing(Path(config.archiving.archive_dir))

    # AI-enhanced briefing (Agent 3)
    if config.ai.enabled and config.ai.briefing_analyst.enabled and briefing.deltas:
        try:
            from scanner.agents.briefing_analyst import BriefingAnalystAgent
            agent = BriefingAnalystAgent(config.ai.briefing_analyst)
            ai_briefing = asyncio.run(agent.analyze(briefing))
            console.print(f"\n [bold]AI BRIEFING[/bold]: {ai_briefing.market_narrative}")
            if ai_briefing.action_summary:
                console.print(f" [cyan]Action:[/cyan] {ai_briefing.action_summary}")
        except Exception:
            pass  # fallback to mechanical rendering below

    if briefing.deltas or briefing.new_markets:
        render_daily_deltas(briefing.deltas, briefing.new_markets)
    else:
        console.print(f"\n [dim]{briefing.summary}[/dim]")

    # Auto-resolve paper trades
    with _open_paper_db(config) as db:
        try:
            from scanner.auto_resolve import auto_resolve_trades
            open_count = len(db.list_open())
            resolved_n = asyncio.run(auto_resolve_trades(db))
            if resolved_n:
                console.print(f"\n [green]Auto-resolved {resolved_n}/{open_count} paper trade(s)[/green]")
            elif open_count > 0:
                console.print(f"\n [dim]{open_count} open paper trades checked, none resolved yet[/dim]")
        except Exception as e:
            console.print(f"\n [dim]Auto-resolve skipped: {e}[/dim]")

        open_trades = db.list_open()
        stats = db.stats()

    if open_trades or stats["resolved"] > 0:
        console.print(
            f"\n [bold]PAPER TRADES[/bold]  Open: {len(open_trades)} | "
            f"Resolved: {stats['resolved']} | Win rate: {stats['win_rate']:.0%}"
        )
        for t in open_trades[:3]:
            console.print(f"   {t.title[:45]}  {t.side.upper()} @ {t.entry_price:.2f}")

        # Graduation progress hint
        from scanner.graduation import MIN_TRADES
        if stats["resolved"] < MIN_TRADES:
            remaining = MIN_TRADES - stats["resolved"]
            console.print(f"   [dim]毕业进度: {stats['resolved']}/{MIN_TRADES} — 还需 {remaining} 笔 resolved trades[/dim]")

        # Overtrading warning
        weekly = db.weekly_stats()
        weekly_friction = db.weekly_friction()
        week_count = weekly["total_trades"]
        max_weekly = config.discipline.max_trades_per_week
        if week_count >= max_weekly:
            console.print(f"   [yellow]⚠ 本周已交易 {week_count} 笔（上限 {max_weekly}），累计摩擦 ${weekly_friction:.2f}。考虑是否过度交易。[/yellow]")
        elif weekly_friction > 0:
            console.print(f"   [dim]本周: {week_count} 笔，累计摩擦 ${weekly_friction:.2f}[/dim]")


@app.command()
def backtest(
    config_path: str = typer.Option(None, "--config", "-c"),
    resolutions_file: str = typer.Option(None, "--resolutions", "-r", help="JSON file: {market_id: 'yes'|'no'}"),
):
    """Analyze historical scans vs actual resolutions."""
    config = _resolve_config(config_path)
    from scanner.backtest import run_backtest

    resolutions = {}
    if resolutions_file:
        with open(resolutions_file) as f:
            resolutions = json.load(f)
    else:
        with _open_paper_db(config) as db:
            for t in db.list_all():
                if t.status == "resolved" and t.resolved_result:
                    resolutions[t.market_id] = t.resolved_result

    result = run_backtest(Path(config.archiving.archive_dir), resolutions)

    if result.total_markets == 0:
        console.print("[dim]No scan archives found. Run some scans first.[/dim]")
        return

    console.print(Panel.fit(
        f"[bold]BACKTEST REPORT[/bold]\n\n"
        f"Archives: {result.total_markets} entries ({result.unique_markets} unique)\n"
        f"Resolved: {result.resolved}\n\n"
        f"[bold]NAIVE YES STRATEGY[/bold]\n"
        f"  Wins: {result.naive_yes_wins} | Losses: {result.naive_yes_losses}\n"
        f"  Paper PnL: ${result.naive_yes_pnl:+.2f}\n"
        f"  Friction-adjusted PnL: ${result.friction_adjusted_pnl:+.2f}\n\n"
        + (f"High-score (≥75) hit rate: {result.high_score_hit_rate:.0%}\n"
           if result.high_score_hit_rate is not None else "")
        + (f"Low-score (<75) hit rate: {result.low_score_hit_rate:.0%}\n"
           if result.low_score_hit_rate is not None else "")
        + (f"\n[bold]DIRECTIONAL STRATEGY[/bold] (follow mispricing signal)\n"
           f"  Trades: {result.directional_trades} | Wins: {result.directional_wins}\n"
           f"  PnL: ${result.directional_pnl:+.2f}\n"
           f"  Friction-adjusted: ${result.directional_friction_pnl:+.2f}\n"
           if result.directional_trades > 0 else "")
        + "\n[dim]Use 'polily resolve <id> -r yes/no' to add resolution data.[/dim]",
        border_style="magenta",
    ))

    render_backtest_tables(result)

    if result.credibility_verdict:
        console.print(Panel(
            f"[bold]工具可信度评估[/bold]\n\n{result.credibility_verdict}",
            border_style="cyan",
        ))


@app.command()
def review(
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """AI-powered paper trading performance review (weekly recommended)."""
    config = _resolve_config(config_path)
    with _open_paper_db(config) as db:
        stats = db.stats()

    if stats["total_trades"] == 0:
        console.print("[dim]No paper trades yet. Use 'polily mark' to start.[/dim]")
        return

    if config.ai.enabled and config.ai.review_analyst.enabled:
        import asyncio

        from scanner.agents.review_analyst import ReviewAnalystAgent
        agent = ReviewAnalystAgent(config.ai.review_analyst)
        try:
            result = asyncio.run(agent.analyze(stats))
        except Exception:
            from scanner.agents.review_analyst import review_fallback
            result = review_fallback(stats)
    else:
        from scanner.agents.review_analyst import review_fallback
        result = review_fallback(stats)

    console.print(Panel(
        f"[bold]PERFORMANCE REVIEW[/bold]\n\n"
        f"[bold]Analysis:[/bold] {result.behavior_analysis}\n\n"
        f"[bold]Calibration:[/bold] {result.calibration_feedback}\n\n"
        f"[bold]Recommendations:[/bold]",
        border_style="magenta",
    ))
    for rec in result.recommendations:
        console.print(f"  [cyan]•[/cyan] {rec}")

    if result.category_insights:
        console.print("\n[bold]Category Insights:[/bold]")
        for insight in result.category_insights:
            console.print(f"  {insight}")


@app.command()
def match(
    view: str = typer.Argument(help="Your view, e.g. 'BTC will hit 70k' or 'Fed will cut rates'"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Find markets matching your directional view."""
    config = _resolve_config(config_path)
    markets = asyncio.run(_fetch_markets(config))

    if not markets:
        console.print("[red]No markets loaded.[/red]")
        raise typer.Exit(1)

    from scanner.match import find_matching_markets
    results = find_matching_markets(view, markets)

    if not results:
        console.print(f"\n [dim]No markets match your view: \"{view}\"[/dim]")
        return

    console.print(f"\n [bold]Markets matching: \"{view}\"[/bold]\n")
    for i, r in enumerate(results[:3], 1):
        m = r.market
        friction = m.round_trip_friction_pct or 0.04
        net_payoff = r.payoff_if_right - (20.0 * friction)
        link = m.polymarket_url

        console.print(f" #{i}  {m.title}")
        if r.relevance_score >= 2:
            # High confidence match: show full payoff
            console.print(f"     {r.suggested_side.upper()} @ {r.cost:.2f} | YES: {m.yes_price:.2f}")
            console.print(f"     如果你对了 ($20): [green]+${net_payoff:.2f}[/green] (扣摩擦)")
            console.print("     如果你错了: [red]-$20.00[/red]")
        else:
            # Low confidence match: show price only, no payoff suggestion
            console.print(f"     YES: {m.yes_price:.2f} | [dim]匹配度低，可能无实际关联[/dim]")
        console.print(f"     [dim]{link}[/dim]")
        console.print("     [yellow]没有方向观点？跳过。Payoff 假设你判断完全正确——这不常发生。[/yellow]\n")


@app.command()
def export(
    what: str = typer.Argument(help="trades 或 scans"),
    output: str = typer.Option("export.csv", "--output", "-o", help="输出文件路径"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Export paper trades or scan history to CSV."""
    config = _resolve_config(config_path)
    from scanner.export import export_scans_csv, export_trades_csv

    if what == "trades":
        with _open_paper_db(config) as db:
            export_trades_csv(db, output)
        console.print(f"[green]✅ 导出 trades → {output}[/green]")
    elif what == "scans":
        export_scans_csv(config.archiving.archive_dir, output)
        console.print(f"[green]✅ 导出 scans → {output}[/green]")
    else:
        console.print("[red]请指定 trades 或 scans[/red]")
        raise typer.Exit(1)


@app.command()
def mark(
    market_id: str = typer.Argument(None, help="Market ID (or use --rank)"),
    rank: int = typer.Option(None, "--rank", "-r", help="Pick by scan rank (#1, #2, ...)"),
    side: str = typer.Option("yes", "--side", "-s", help="yes or no"),
    price: float = typer.Option(None, "--price", "-p", help="Entry price (auto-filled if omitted)"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Mark a paper trade."""
    if side not in ("yes", "no"):
        console.print("[red]--side must be 'yes' or 'no'[/red]")
        raise typer.Exit(1)

    config = _resolve_config(config_path)
    archive_dir = config.archiving.archive_dir

    # Resolve from --rank
    title = None
    if rank is not None:
        entry = find_entry_by_rank(rank, archive_dir)
        if entry is None:
            console.print(f"[red]No candidate at rank #{rank} in latest scan.[/red]")
            raise typer.Exit(1)
        market_id = entry.get("market_id", market_id)
        title = entry.get("title", market_id)
        if price is None:
            price = entry.get("yes_price") if side == "yes" else entry.get("no_price")

    if market_id is None:
        console.print("[red]Provide market_id or use --rank.[/red]")
        raise typer.Exit(1)

    # Enrich from archive
    entry = find_entry_in_archive(market_id, archive_dir) or {}
    if title is None:
        title = entry.get("title", market_id)
    if price is None:
        price = entry.get("yes_price")
    if price is None:
        console.print("[red]No price found. Use --price to specify.[/red]")
        raise typer.Exit(1)

    with _open_paper_db(config) as db:
        from scanner.archive import get_latest_scan_id
        scan_id = get_latest_scan_id(config.archiving.archive_dir)
        trade = db.mark(
            market_id=market_id, title=title, side=side, entry_price=price,
            market_type=entry.get("market_type"),
            structure_score=entry.get("structure_score"),
            mispricing_signal=entry.get("mispricing_signal"),
            scan_id=scan_id,
        )

    console.print(f"[green]Paper trade marked:[/green] {trade.id}")
    console.print(f"  {title}")
    console.print(f"  Side: {side.upper()} | Entry: {price:.2f} | Notional: ${config.paper_trading.default_position_size_usd}")


@app.command(name="paper-status")
def paper_status(config_path: str = typer.Option(None, "--config", "-c")):
    """Show open paper trade positions."""
    config = _resolve_config(config_path)
    with _open_paper_db(config) as db:
        open_trades = db.list_open()

    if not open_trades:
        console.print("[dim]No open paper trades. Use 'polily mark <market_id>' to start.[/dim]")
        return

    table = Table(title="Open Paper Trades")
    table.add_column("ID", style="cyan")
    table.add_column("Market")
    table.add_column("Side")
    table.add_column("Entry")
    table.add_column("Marked")
    for t in open_trades:
        table.add_row(t.id, t.title[:45], t.side.upper(), f"{t.entry_price:.2f}", t.marked_at[:10])
    console.print(table)


@app.command(name="paper-report")
def paper_report(
    days: int = typer.Option(30, "--days", "-d", help="Report period in days"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Paper trading performance report."""
    config = _resolve_config(config_path)
    with _open_paper_db(config) as db:
        stats = db.stats(days=days)

    if stats["total_trades"] == 0:
        console.print("[dim]No paper trades yet. Use 'polily mark' to start.[/dim]")
        return

    sample_note = ""
    if stats["resolved"] < 10:
        sample_note = "\n[yellow]Note: < 10 resolved trades. Statistics not yet meaningful.[/yellow]"

    console.print(Panel.fit(
        f"[bold]PAPER TRADING REPORT[/bold]  (last {days} days)\n\n"
        f"Total: {stats['total_trades']} | Open: {stats['open']} | Resolved: {stats['resolved']}\n"
        f"Wins: {stats['wins']} | Losses: {stats['losses']} | Win rate: {stats['win_rate']:.0%}\n\n"
        f"Paper PnL: ${stats['total_paper_pnl']:+.2f}\n"
        f"Friction-adjusted PnL: ${stats['total_friction_adjusted_pnl']:+.2f}\n\n"
        f"[dim]Friction: {config.paper_trading.assumed_round_trip_friction_pct:.0%} round-trip[/dim]"
        f"{sample_note}",
        border_style="cyan",
    ))

    # Graduation assessment
    from scanner.graduation import assess_graduation
    with _open_paper_db(config) as db2:
        grad = assess_graduation(db2)
    color = "green" if grad.ready else "yellow"
    console.print(f"\n [{color} bold]GRADUATION ASSESSMENT[/{color} bold]")
    for check in grad.checks:
        icon = "[green]✓[/green]" if check.passed else "[red]✗[/red]"
        console.print(f"  {icon} {check.name}: {check.detail}")
    console.print(f"\n  [{color}]{grad.reason}[/{color}]")


@app.command()
def resolve(
    trade_id: str = typer.Argument(help="Paper trade ID (from 'polily paper-status')"),
    result: str = typer.Option(..., "--result", "-r", help="yes or no"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Resolve a paper trade with actual outcome."""
    if result not in ("yes", "no"):
        console.print("[red]--result must be 'yes' or 'no'[/red]")
        raise typer.Exit(1)

    config = _resolve_config(config_path)
    with _open_paper_db(config) as db:
        try:
            trade = db.resolve(trade_id, result=result)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e

    color = "green" if trade.paper_pnl is not None and trade.paper_pnl > 0 else "red"
    console.print(f"[{color}]Resolved:[/{color}] {trade.id} → {result.upper()}")
    console.print(f"  Paper PnL: ${trade.paper_pnl:+.2f}")
    console.print(f"  Friction-adjusted: ${trade.friction_adjusted_pnl:+.2f}")


# --- WATCH lifecycle commands ---


@app.command(name="watch-list")
def watch_list(config_path: str = typer.Option(None, "--config", "-c")):
    """Show all WATCH markets with next_check_at."""
    config = _resolve_config(config_path)
    db = _open_db(config)
    from scanner.market_state import get_watched_markets
    watched = get_watched_markets(db)
    if not watched:
        console.print("[dim]No markets being watched.[/dim]")
        return
    from rich.table import Table
    table = Table(title="WATCH Markets")
    table.add_column("Market", style="cyan")
    table.add_column("Next Check", style="yellow")
    table.add_column("Reason", style="dim")
    table.add_column("#", style="magenta", justify="right")
    table.add_column("Auto", style="green", justify="center")
    for mid, state in watched.items():
        table.add_row(
            state.title[:40] or mid[:12],
            state.next_check_at[:16] if state.next_check_at else "-",
            state.watch_reason or "-",
            str(state.watch_sequence),
            "ON" if state.auto_monitor else "-",
        )
    console.print(table)
    db.close()


@app.command(name="pass-market")
def pass_market(
    market_id: str = typer.Argument(help="Market ID to mark as PASS"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Mark a market as PASS — stop watching."""
    from datetime import datetime

    config = _resolve_config(config_path)
    db = _open_db(config)
    from scanner.market_state import MarketState, get_market_state, set_market_state
    state = get_market_state(market_id, db)
    if state is None:
        console.print(f"[red]Market {market_id} not found.[/red]")
        raise typer.Exit(1)
    state.status = "pass"
    state.updated_at = datetime.now(UTC).isoformat()
    state.auto_monitor = False
    state.next_check_at = None
    state.watch_reason = None
    set_market_state(market_id, state, db)
    console.print(f"[green]PASS:[/green] {state.title or market_id}")
    db.close()


@app.command(name="watch")
def watch_toggle(
    market_id: str = typer.Argument(help="Market ID"),
    enable: bool = typer.Option(False, "--enable", help="Enable auto-monitor"),
    disable: bool = typer.Option(False, "--disable", help="Disable auto-monitor"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Enable or disable auto-monitor for a WATCH market."""
    from datetime import datetime

    config = _resolve_config(config_path)
    db = _open_db(config)
    from scanner.market_state import get_market_state, set_market_state
    state = get_market_state(market_id, db)
    if state is None:
        console.print(f"[red]Market {market_id} not found.[/red]")
        raise typer.Exit(1)
    if enable:
        state.auto_monitor = True
    elif disable:
        state.auto_monitor = False
    else:
        console.print("[dim]Use --enable or --disable[/dim]")
        raise typer.Exit(1)
    state.updated_at = datetime.now(UTC).isoformat()
    set_market_state(market_id, state, db)
    label = "ON" if state.auto_monitor else "OFF"
    console.print(f"Auto-monitor [{label}]: {state.title or market_id}")
    db.close()


@app.command(name="check")
def check_market(
    market_id: str = typer.Argument(help="Market ID to recheck"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Recheck a single WATCH market — fetch latest data + AI re-evaluation."""
    config = _resolve_config(config_path)
    db = _open_db(config)
    from scanner.watch_recheck import recheck_market
    try:
        result = recheck_market(market_id, db=db, trigger_source="manual")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    labels = {"buy_yes": "GO BUY YES", "buy_no": "GO BUY NO",
              "watch": "WATCH", "pass": "PASS", "closed": "CLOSED"}
    label = labels.get(result.new_status, result.new_status)
    color = "green" if result.new_status in ("buy_yes", "buy_no") else "yellow" if result.new_status == "watch" else "dim"
    console.print(f"[{color}][{label}][/{color}] {market_id[:16]}")
    if result.previous_price and result.current_price:
        delta = (result.current_price - result.previous_price) / result.previous_price * 100
        console.print(f"  YES: {result.previous_price:.2f} → {result.current_price:.2f} ({delta:+.1f}%)")
    if result.next_check_at:
        console.print(f"  Next check: {result.next_check_at[:16]}")
    if result.reason:
        console.print(f"  Reason: {result.reason}")
    db.close()


# --- Helpers ---


ACTION_CHECKLIST = """\
  下一步:
  [ ] 1. 在 Polymarket 上打开此市场，读 resolution rules
  [ ] 2. 问自己: 我对结果有观点吗？（没观点就跳过）
  [ ] 3. 检查: 我的观点来源是什么？（新闻/数据/直觉）
  [ ] 4. 如果想试: polily mark --rank {rank} --side yes (模拟下注，不花真钱)
  [ ] 5. 设心理止损: 如果亏 ${max_loss} 就认输，不加仓"""


def _render_simple_mode(tiers, config):
    from scanner.render import render_candidate_simple

    if not tiers.tier_a and not tiers.tier_b:
        console.print("\n [dim]今天没有通过筛选的市场。这很正常。[/dim]")
        return

    console.print(" [dim]质量分过滤了垃圾市场，但不预测涨跌。你来做判断。[/dim]")

    idx = 1
    if tiers.tier_a:
        console.print(f"\n [green bold]值得研究 ({len(tiers.tier_a)})[/green bold]")
        for c in tiers.tier_a:
            console.print(render_candidate_simple(idx, c))
            console.print(ACTION_CHECKLIST.format(rank=idx, max_loss=int(config.discipline.max_single_trade_usd)))
            console.print()
            idx += 1

    watchlist = tiers.tier_b[:5]
    if watchlist:
        console.print(f"\n [yellow bold]--- 观察列表 ({len(watchlist)}) ---[/yellow bold]")
        for c in watchlist:
            console.print(render_candidate_simple(idx, c))
            idx += 1


async def _fetch_markets(config: ScannerConfig) -> list:
    client = PolymarketClient(config.api)
    try:
        with console.status("Fetching markets from Polymarket..."):
            events = await client.fetch_all_events(
                max_events=config.scanner.max_markets_to_fetch // 2,
            )
        markets = []
        for event in events:
            markets.extend(parse_gamma_event(event))
        console.print(f" [dim]Fetched {len(markets)} markets from {len(events)} events[/dim]")
        return markets
    finally:
        await client.close()


if __name__ == "__main__":
    app()
