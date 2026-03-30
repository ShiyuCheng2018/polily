"""Paper trading graduation: assess if user is ready for real money."""

from dataclasses import dataclass, field

from scanner.paper_trading import PaperTradingDB

MIN_TRADES = 10
MIN_WIN_RATE = 0.45
MAX_CONSECUTIVE_LOSSES = 5


@dataclass
class GraduationCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class GraduationResult:
    ready: bool
    checks: list[GraduationCheck] = field(default_factory=list)
    reason: str = ""


def assess_graduation(db: PaperTradingDB) -> GraduationResult:
    """Assess whether paper trading results justify moving to real money."""
    stats = db.stats()
    all_trades = db.list_all()
    resolved = sorted(
        [t for t in all_trades if t.status == "resolved"],
        key=lambda t: t.marked_at,
    )

    checks = []

    # Check 1: Minimum trade count
    count_ok = stats["resolved"] >= MIN_TRADES
    checks.append(GraduationCheck(
        name="Trade count",
        passed=count_ok,
        detail=f"{stats['resolved']}/{MIN_TRADES} resolved trades",
    ))

    # Check 2: Friction-adjusted PnL positive
    pnl = stats.get("total_friction_adjusted_pnl", 0)
    pnl_ok = pnl > 0 and stats["resolved"] >= MIN_TRADES
    checks.append(GraduationCheck(
        name="Friction-adjusted PnL",
        passed=pnl_ok,
        detail=f"${pnl:+.2f}",
    ))

    # Check 3: Win rate above minimum
    wr = stats.get("win_rate", 0)
    wr_ok = wr >= MIN_WIN_RATE and stats["resolved"] >= MIN_TRADES
    checks.append(GraduationCheck(
        name="Win rate",
        passed=wr_ok,
        detail=f"{wr:.0%} (min {MIN_WIN_RATE:.0%})",
    ))

    # Check 4: Max single loss within limit
    max_single_loss = max(
        (abs(t.paper_pnl) for t in resolved if t.paper_pnl is not None and t.paper_pnl < 0),
        default=0,
    )
    max_trade_usd = db.position_size_usd
    single_loss_ok = max_single_loss <= max_trade_usd
    checks.append(GraduationCheck(
        name="Max single loss",
        passed=single_loss_ok,
        detail=f"${max_single_loss:.2f} (limit ${max_trade_usd:.0f})",
    ))

    # Check 5: No excessive consecutive losses
    max_streak = _max_loss_streak(resolved)
    streak_ok = max_streak < MAX_CONSECUTIVE_LOSSES
    checks.append(GraduationCheck(
        name="Max consecutive losses",
        passed=streak_ok,
        detail=f"{max_streak} (max {MAX_CONSECUTIVE_LOSSES})",
    ))

    all_passed = all(c.passed for c in checks)

    if not count_ok:
        remaining = MIN_TRADES - stats["resolved"]
        reason = f"还需 {remaining} 笔 resolved trades（目前 {stats['resolved']}）。继续 paper trading。"
    elif not all_passed:
        # Diagnostic advice based on which checks failed
        diagnostics = []
        if not pnl_ok:
            diagnostics.append("扣除成本后盈亏为负——试试选 spread 更低（成本更小）的市场")
        if not wr_ok:
            diagnostics.append("胜率偏低——检查你的方向判断，是否在没有观点时强行交易？")
        if not single_loss_ok:
            diagnostics.append(f"单笔最大亏损 ${max_single_loss:.0f} 超限——严格控制每笔投入")
        if not streak_ok:
            diagnostics.append(f"连续亏损 {max_streak} 笔——情绪管理很重要，连亏后暂停一天")
        reason = "暂不建议转真钱。" + " ".join(diagnostics)
    else:
        reason = f"数据显示你可能有 edge。建议从小额真钱开始（$5-10/笔），但 {stats['resolved']} 笔样本量仍然很小。"

    return GraduationResult(ready=all_passed, checks=checks, reason=reason)


def _max_loss_streak(resolved_trades) -> int:
    """Find the longest consecutive loss streak."""
    max_streak = 0
    current = 0
    for t in resolved_trades:
        if t.paper_pnl is not None and t.paper_pnl <= 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak
