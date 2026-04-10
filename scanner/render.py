"""Terminal rendering: dashboard, candidate cards, deep dive, tier lists."""

from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scanner.core.config import ScannerConfig
from scanner.scan.reporting import ScoredCandidate, TierResult

console = Console()


def render_dashboard(tiers: TierResult, config: ScannerConfig, total_scanned: int = 0):
    scored = len(tiers.tier_a) + len(tiers.tier_b) + len(tiers.tier_c)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    friction_lines = ""
    if tiers.tier_a:
        frictions = [c.market.round_trip_friction_pct for c in tiers.tier_a if c.market.round_trip_friction_pct]
        avg_f = sum(frictions) / len(frictions) if frictions else 0
        edge_gt = sum(
            1 for c in tiers.tier_a
            if (c.mispricing.deviation_pct or 0) > (c.market.round_trip_friction_pct or 0)
        )
        friction_lines = (
            f"\n摩擦检查: 平均来回 {avg_f:.1%} | "
            f"Edge > 摩擦: {edge_gt}/{len(tiers.tier_a)}"
        )

    calendar_lines = ""
    if config.calendar.enabled:
        from scanner.calendar_events import (
            find_upcoming_events,
            generate_cross_domain_notes,
            load_calendar,
            match_markets_to_events,
        )
        events = load_calendar(Path(config.calendar.calendar_file))
        upcoming = find_upcoming_events(events, datetime.now(UTC), config.calendar.lookahead_days)
        if upcoming:
            event_strs = []
            for e in upcoming[:3]:
                icon = "[!]" if e.impact == "high" else "[i]"
                event_strs.append(f"{icon} {e.name} ({e.date}) — {e.impact.upper()}")
            calendar_lines = "\n\nTODAY'S CONTEXT\n" + "\n".join(event_strs)

            if config.calendar.cross_domain_linking:
                all_markets = [c.market for c in tiers.tier_a + tiers.tier_b[:5]]
                pairs = match_markets_to_events(all_markets, upcoming)
                if pairs:
                    cross_notes = generate_cross_domain_notes(pairs)
                    if cross_notes:
                        calendar_lines += "\n\nCROSS-DOMAIN\n" + "\n".join(cross_notes[:2])

    console.print(Panel.fit(
        f"[bold]POLILY SCANNER[/bold]  {now}\n\n"
        f"扫描: {total_scanned} | 通过: {scored} | "
        f"[green]研究: {len(tiers.tier_a)}[/green] | "
        f"[yellow]观察: {len(tiers.tier_b)}[/yellow] | "
        f"[dim]过滤: {len(tiers.tier_c)}[/dim]"
        f"{friction_lines}"
        f"{calendar_lines}\n\n"
        f"[dim]结构评分过滤噪音，不预测方向和盈利。[/dim]",
        border_style="blue",
    ))


def render_candidate_card(idx: int, c: ScoredCandidate, verbose: bool = False, show_lean: bool = False):
    m = c.market
    s = c.score
    mp = c.mispricing

    days_str = f"{m.days_to_resolution:.1f}d" if m.days_to_resolution else "?"
    spread_str = f"{m.spread_pct_yes:.1%}" if m.spread_pct_yes else "?"
    friction_str = f"~{m.round_trip_friction_pct:.1%}" if m.round_trip_friction_pct else "?"
    bid_depth = f"${m.total_bid_depth_usd:,.0f}" if m.total_bid_depth_usd else "?"
    ask_depth = f"${m.total_ask_depth_usd:,.0f}" if m.total_ask_depth_usd else "?"
    mp_color = {"strong": "red", "moderate": "yellow", "weak": "dim"}.get(mp.signal, "dim")

    console.print(f"\n [bold]#{idx}[/bold]  {m.title}  [bold]结构分: {s.total:.0f}/100[/bold]")
    link = m.polymarket_url
    console.print(f"     类型: {m.market_type or '?'} | 结算: {days_str}")
    console.print(f"     [dim]{link}[/dim]")
    console.print(
        f"     YES {m.yes_price:.2f} | NO {m.no_price or 0:.2f} | "
        f"价差: {spread_str} | 摩擦: {friction_str}"
    )
    console.print(f"     深度: 买 {bid_depth} / 卖 {ask_depth}")
    if mp.signal != "none":
        console.print(f"     Mispricing: [{mp_color}]{mp.signal.upper()}[/{mp_color}] — {mp.details}")
    # Conditional advice (only when show_lean is enabled)
    if show_lean and mp.direction and mp.signal != "none" and mp.model_confidence in ("high", "medium"):
        if mp.direction == "overpriced":
            console.print("     [yellow]如果你看跌[/yellow]: YES 可能被高估，买 NO 可能有 edge")
        else:
            console.print("     [green]如果你看涨[/green]: YES 可能被低估，买 YES 可能有 edge")
        console.print("     [yellow]没有方向观点？跳过。[/yellow]")

    if c.narrative:
        n = c.narrative
        console.print(f"     [bold]AI 分析:[/bold] {n.summary}")

    if verbose:
        render_deep_dive(c)


def render_deep_dive(c: ScoredCandidate):
    """Layer 2: detailed score breakdown + risk analysis."""
    s = c.score
    m = c.market
    mp = c.mispricing

    console.print("\n     [bold]结构评分明细[/bold]")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Component", style="dim")
    table.add_column("Score", justify="right")
    for name, val, max_val in [
        ("流动性结构", s.liquidity_structure, 30),
        ("客观可验证性", s.objective_verifiability, 25),
        ("概率空间", s.probability_space, 20),
        ("时间结构", s.time_structure, 15),
        ("交易摩擦", s.trading_friction, 10),
    ]:
        table.add_row(f"     {name}", f"{val:.1f}/{max_val}")
    console.print(table)

    if mp.signal != "none" and mp.details:
        console.print(f"\n     [bold]MISPRICING[/bold]: {mp.details}")
        if mp.theoretical_fair_value:
            console.print(f"     Model fair value: {mp.theoretical_fair_value:.2f} | Market: {m.yes_price:.2f}")

    if c.narrative:
        n = c.narrative
        console.print("\n     [bold]风险提示[/bold]")
        for flag in n.risk_flags:
            console.print(f"     [red]•[/red] {flag}")
        console.print(f"\n     [bold]对手方[/bold]: {n.counterparty_note}")
    elif m.market_type:
        # Static checklist fallback when no AI narrative
        from scanner.checklist import load_checklist
        steps = load_checklist(m.market_type)
        if steps:
            console.print("\n     [bold]RESEARCH CHECKLIST[/bold]")
            for item in steps:
                console.print(f"     [ ] {item}")

    # Scenario calculator ($20 position, side-aware)
    pos_size = 20.0
    if m.yes_price and m.yes_price > 0:
        friction_cost = pos_size * (m.round_trip_friction_pct or 0.04)

        # Determine which side to calculate for
        if mp.direction == "overpriced":
            # Lean suggests NO
            side_price = 1.0 - m.yes_price
            side_label = "NO"
        else:
            side_price = m.yes_price
            side_label = "YES"

        if side_price > 0:
            gross_profit = (pos_size / side_price) * 1.0 - pos_size
            breakeven_move = friction_cost / (pos_size / side_price)
        else:
            gross_profit = 0
            breakeven_move = 0

        console.print(f"\n     [bold]投入 ${pos_size:.0f} 买 {side_label}:[/bold]")
        console.print(f"     最坏: [red]-${pos_size:.2f}[/red]（归零）")
        console.print(f"     摩擦: -${friction_cost:.2f}")
        console.print(f"     打平: 价格需移动 +${breakeven_move:.2f}")
        console.print(f"     判断对: [green]+${gross_profit - friction_cost:.2f}[/green]（扣摩擦）")


def render_tier_a(tiers: TierResult, verbose: bool = False, show_lean: bool = False):
    all_candidates = sorted(tiers.tier_a + tiers.tier_b, key=lambda c: c.score.total, reverse=True)

    if not all_candidates:
        console.print("\n [dim]今日跳过：没有通过筛选的候选。好机会不是每天都有，休息也是策略。[/dim]")
        return

    # Top Pick: the single best candidate
    top = all_candidates[0]
    console.print("\n [green bold]今日首选[/green bold]")
    render_candidate_card(1, top, verbose=verbose, show_lean=show_lean)

    rest = all_candidates[1:4]
    if rest:
        console.print(f"\n [yellow bold]也值得关注 ({len(rest)})[/yellow bold]")
        for i, c in enumerate(rest, 2):
            m = c.market
            days_str = f"{m.days_to_resolution:.1f}d" if m.days_to_resolution else "?"
            spread_str = f"{m.spread_pct_yes:.1%}" if m.spread_pct_yes else "?"
            title = m.title[:55] + "..." if len(m.title) > 55 else m.title
            console.print(
                f" #{i}  {title}  "
                f"Str: {c.score.total:.0f} | YES {m.yes_price:.2f} | Spr {spread_str} | {days_str}"
            )


def render_tier_b(tiers: TierResult, limit: int = 5):
    if not tiers.tier_b:
        return
    shown = tiers.tier_b[:limit]
    console.print(f"\n [yellow bold]WATCHLIST (top {len(shown)} of {len(tiers.tier_b)})[/yellow bold]")
    for i, c in enumerate(shown, len(tiers.tier_a) + 1):
        m = c.market
        days_str = f"{m.days_to_resolution:.1f}d" if m.days_to_resolution else "?"
        spread_str = f"{m.spread_pct_yes:.1%}" if m.spread_pct_yes else "?"
        title = m.title[:55] + "..." if len(m.title) > 55 else m.title
        console.print(
            f" #{i}  {title}  "
            f"Str: {c.score.total:.0f} | YES {m.yes_price:.2f} | Spr {spread_str} | {days_str}"
        )


def render_candidate_simple(idx: int, c: ScoredCandidate) -> str:
    """Render a candidate in newbie-friendly simple mode. Returns a string."""
    m = c.market
    s = c.score

    days_str = f"{m.days_to_resolution:.1f}天" if m.days_to_resolution else "?"
    friction = m.round_trip_friction_pct
    cost_str = f"~{friction:.1%}" if friction else "?"

    # Simplified depth
    bid = m.total_bid_depth_usd
    if bid is None:
        depth_str = "未知"
    elif bid >= 1000:
        depth_str = "够用"
    elif bid >= 200:
        depth_str = "勉强"
    else:
        depth_str = "不够"

    if m.yes_price:
        yes_str = f"{m.yes_price:.2f}"
        prob_line = f"    概率: {yes_str} (买YES花${yes_str}/份, 赢得$1.00/份)"
    else:
        prob_line = "    概率: 未知"

    # Cost level indicator
    if friction and friction < 0.03:
        cost_level = "低"
    elif friction and friction < 0.06:
        cost_level = "中等"
    else:
        cost_level = "偏高"

    # One-sentence score explanation: top 2 reasons
    score_reasons = []
    if s.liquidity_structure >= 20:
        score_reasons.append("流动性好")
    if s.objective_verifiability >= 18:
        score_reasons.append("结算清晰")
    if s.probability_space >= 14:
        score_reasons.append("概率适中")
    if s.time_structure >= 10:
        score_reasons.append("时间合适")
    if s.trading_friction >= 7:
        score_reasons.append("摩擦低")
    score_why = "，".join(score_reasons[:2]) if score_reasons else "综合表现不错"

    link = m.polymarket_url
    lines = [
        f"#{idx}  {m.title}",
        prob_line,
        f"    时间: {days_str}后结算",
        f"    质量: {s.total:.0f}/100 — {score_why} (高分≠能赚钱)",
        f"    成本: 买卖一轮约{cost_str} — {cost_level} (隐形手续费)",
        f"    深度: {depth_str} ($20不会被吃)",
        f"    链接: {link}",
    ]
    return "\n".join(lines)


def render_daily_deltas(deltas, new_markets):
    """Render yesterday-to-today delta tracking with context."""

    if deltas:
        console.print("\n [bold]YESTERDAY'S CANDIDATES — TRACKING[/bold]")
        table = Table(show_header=True)
        table.add_column("Market", max_width=40)
        table.add_column("Yesterday", justify="right")
        table.add_column("Today", justify="right")
        table.add_column("Change", justify="right")
        table.add_column("Context")

        for d in deltas:
            y_str = f"{d.yesterday_price:.2f}" if d.yesterday_price else "?"
            if d.disappeared:
                t_str, chg_str = "—", "—"
                context = "[dim]Resolved/Removed[/dim]"
            elif d.today_price is not None:
                t_str = f"{d.today_price:.2f}"
                if d.price_change_pct is not None:
                    color = "green" if d.price_change_pct > 0 else "red"
                    chg_str = f"[{color}]{d.price_change_pct:+.1%}[/{color}]"
                else:
                    chg_str = "—"
                # Delta context: explain what the movement means
                context = _delta_context(d)
            else:
                t_str, chg_str, context = "?", "?", ""
            table.add_row(d.title[:40], y_str, t_str, chg_str, context)
        console.print(table)

    if new_markets:
        console.print(f"\n [cyan]NEW SINCE YESTERDAY: {len(new_markets)} markets[/cyan]")
        for m in new_markets[:3]:
            console.print(f"   + {m.get('title', '?')[:55]}  Score: {m.get('structure_score', '?')}")


def _delta_context(d) -> str:
    """Generate brief context for a price movement."""
    if d.price_change_pct is None:
        return ""
    pct = abs(d.price_change_pct)
    if pct > 0.15:
        return "[bold]Big move[/bold] — check what happened"
    elif pct > 0.05:
        return "Notable shift — worth reviewing"
    elif pct < 0.01:
        return "[dim]Stable[/dim]"
    return ""


def render_backtest_tables(result):
    """Render backtest result tables."""
    if result.by_mispricing_signal:
        table = Table(title="By Mispricing Signal")
        table.add_column("Signal")
        table.add_column("Count", justify="right")
        table.add_column("Resolved", justify="right")
        table.add_column("Hit Rate", justify="right")
        table.add_column("PnL", justify="right")
        table.add_column("After Friction", justify="right")
        for sig, stats in sorted(result.by_mispricing_signal.items()):
            table.add_row(
                sig, str(stats.count), str(stats.resolved),
                f"{stats.hit_rate:.0%}" if stats.resolved > 0 else "—",
                f"${stats.pnl:+.2f}" if stats.resolved > 0 else "—",
                f"${stats.friction_pnl:+.2f}" if stats.resolved > 0 else "—",
            )
        console.print(table)

    if result.by_market_type:
        table = Table(title="By Market Type")
        table.add_column("Type")
        table.add_column("Count", justify="right")
        table.add_column("Resolved", justify="right")
        table.add_column("Hit Rate", justify="right")
        table.add_column("PnL", justify="right")
        table.add_column("After Friction", justify="right")
        for mtype, stats in sorted(result.by_market_type.items()):
            table.add_row(
                mtype, str(stats.count), str(stats.resolved),
                f"{stats.hit_rate:.0%}" if stats.resolved > 0 else "—",
                f"${stats.pnl:+.2f}" if stats.resolved > 0 else "—",
                f"${stats.friction_pnl:+.2f}" if stats.resolved > 0 else "—",
            )
        console.print(table)

    if result.by_score_range:
        table = Table(title="By Structure Score Range")
        table.add_column("Range")
        table.add_column("Count", justify="right")
        table.add_column("Resolved", justify="right")
        table.add_column("Hit Rate", justify="right")
        table.add_column("After Friction", justify="right")
        table.add_column("Confidence", justify="right")
        for label in ["<60", "60-69", "70-79", "80-89", "90+"]:
            stats = result.by_score_range.get(label)
            if stats and stats.count > 0:
                if stats.resolved >= 20:
                    conf = "[green]n≥20[/green]"
                elif stats.resolved >= 10:
                    conf = "[yellow]n≥10[/yellow]"
                elif stats.resolved > 0:
                    conf = f"[red]n={stats.resolved}[/red]"
                else:
                    conf = "[dim]—[/dim]"
                table.add_row(
                    label, str(stats.count), str(stats.resolved),
                    f"{stats.hit_rate:.0%}" if stats.resolved > 0 else "—",
                    f"${stats.friction_pnl:+.2f}" if stats.resolved > 0 else "—",
                    conf,
                )
        console.print(table)
