"""Backtest analyzer: compare archived scan results vs actual market resolutions."""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

POSITION_SIZE = 20.0

SCORE_RANGES = [
    ("60-69", 60, 70),
    ("70-79", 70, 80),
    ("80-89", 80, 90),
    ("90+", 90, 200),
]


@dataclass
class GroupStats:
    count: int = 0
    resolved: int = 0
    wins: int = 0
    pnl: float = 0.0
    friction_pnl: float = 0.0

    @property
    def hit_rate(self) -> float:
        return self.wins / self.resolved if self.resolved > 0 else 0.0


@dataclass
class BacktestResult:
    total_markets: int = 0
    unique_markets: int = 0
    resolved: int = 0
    naive_yes_pnl: float = 0.0
    friction_adjusted_pnl: float = 0.0
    naive_yes_wins: int = 0
    naive_yes_losses: int = 0
    # Directional backtest: follow mispricing signal direction
    directional_pnl: float = 0.0
    directional_friction_pnl: float = 0.0
    directional_trades: int = 0
    directional_wins: int = 0
    high_score_hit_rate: float | None = None
    low_score_hit_rate: float | None = None
    by_mispricing_signal: dict[str, GroupStats] = field(default_factory=dict)
    by_market_type: dict[str, GroupStats] = field(default_factory=dict)
    by_score_range: dict[str, GroupStats] = field(default_factory=dict)
    # Meta judgment
    credibility_verdict: str = ""


def load_all_archives(archive_dir: Path) -> list[list[dict]]:
    if not archive_dir.exists():
        return []
    archives = []
    for path in sorted(archive_dir.glob("*.json")):
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                archives.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping archive %s: %s", path, e)
    return archives


def _score_range_label(score: float) -> str:
    for label, lo, hi in SCORE_RANGES:
        if lo <= score < hi:
            return label
    return "<60"


def run_backtest(
    archive_dir: Path,
    resolutions: dict[str, str],
    score_threshold: float = 75,
) -> BacktestResult:
    archives = load_all_archives(archive_dir)
    if not archives:
        return BacktestResult()

    seen: dict[str, dict] = {}
    total = 0
    for archive in archives:
        for entry in archive:
            total += 1
            mid = entry.get("market_id")
            if mid and mid not in seen:
                seen[mid] = entry

    result = BacktestResult(total_markets=total, unique_markets=len(seen))

    by_mispricing: dict[str, GroupStats] = defaultdict(GroupStats)
    by_type: dict[str, GroupStats] = defaultdict(GroupStats)
    by_range: dict[str, GroupStats] = defaultdict(GroupStats)
    high_score = GroupStats()
    low_score = GroupStats()

    for mid, entry in seen.items():
        yes_price = entry.get("yes_price")
        score = entry.get("structure_score", 0)
        signal = entry.get("mispricing_signal", "none")
        mtype = entry.get("market_type", "other")
        friction_pct = entry.get("round_trip_friction_pct", 0.04)
        range_label = _score_range_label(score)

        by_mispricing[signal].count += 1
        by_type[mtype].count += 1
        by_range[range_label].count += 1
        if score >= score_threshold:
            high_score.count += 1
        else:
            low_score.count += 1

        resolution = resolutions.get(mid)
        if resolution is None or yes_price is None:
            continue

        result.resolved += 1
        by_mispricing[signal].resolved += 1
        by_type[mtype].resolved += 1
        by_range[range_label].resolved += 1

        shares = POSITION_SIZE / yes_price if yes_price > 0 else 0
        friction_cost = POSITION_SIZE * (friction_pct or 0.04)

        if resolution == "yes":
            pnl = shares * 1.0 - POSITION_SIZE
            result.naive_yes_pnl += pnl
            result.friction_adjusted_pnl += pnl - friction_cost
            result.naive_yes_wins += 1

            for group in (by_mispricing[signal], by_type[mtype], by_range[range_label]):
                group.wins += 1
                group.pnl += pnl
                group.friction_pnl += pnl - friction_cost

            if score >= score_threshold:
                high_score.resolved += 1
                high_score.wins += 1
            else:
                low_score.resolved += 1
                low_score.wins += 1
        else:
            pnl = -POSITION_SIZE
            result.naive_yes_pnl += pnl
            result.friction_adjusted_pnl += pnl - friction_cost
            result.naive_yes_losses += 1

            for group in (by_mispricing[signal], by_type[mtype], by_range[range_label]):
                group.pnl += pnl
                group.friction_pnl += pnl - friction_cost

            if score >= score_threshold:
                high_score.resolved += 1
            else:
                low_score.resolved += 1

        # Directional backtest: follow mispricing signal direction
        mispricing_dir = entry.get("mispricing_direction")
        if not mispricing_dir:
            # Fallback: parse from details text for older archives
            mispricing_details = entry.get("mispricing_details", "")
            if "overpriced" in (mispricing_details or "").lower():
                mispricing_dir = "overpriced"
            elif "underpriced" in (mispricing_details or "").lower():
                mispricing_dir = "underpriced"
        if signal not in ("none", "weak") and mispricing_dir:
            suggested_side = "no" if mispricing_dir == "overpriced" else "yes"
            result.directional_trades += 1
            if suggested_side == "yes":
                d_pnl = (shares * 1.0 - POSITION_SIZE) if resolution == "yes" else -POSITION_SIZE
            else:  # buy NO
                no_price = 1.0 - yes_price if yes_price else 0.5
                no_shares = POSITION_SIZE / no_price if no_price > 0 else 0
                d_pnl = (no_shares * 1.0 - POSITION_SIZE) if resolution == "no" else -POSITION_SIZE
            result.directional_pnl += d_pnl
            result.directional_friction_pnl += d_pnl - friction_cost
            if d_pnl > 0:
                result.directional_wins += 1

    result.by_mispricing_signal = dict(by_mispricing)
    result.by_market_type = dict(by_type)
    result.by_score_range = dict(by_range)
    result.high_score_hit_rate = high_score.hit_rate if high_score.resolved > 0 else None
    result.low_score_hit_rate = low_score.hit_rate if low_score.resolved > 0 else None

    # Credibility verdict
    result.credibility_verdict = _assess_credibility(result)

    return result


def _assess_credibility(result: BacktestResult) -> str:
    """Generate a plain-language credibility assessment with baseline comparison."""
    if result.resolved < 5:
        return "数据太少，无法评估。继续积累 scan 和 resolution 数据。"

    parts = []
    alpha = 0.0  # default: no alpha signal

    # Directional signal evaluation
    if result.directional_trades > 0:
        dir_wr = result.directional_wins / result.directional_trades
        parts.append(f"方向准确率 {dir_wr:.0%}（{result.directional_trades} 笔）。")

        if result.directional_trades >= 5:
            # Alpha = directional win rate - naive YES win rate (baseline)
            # Note: baseline uses all resolved markets, not just directional subset
            naive_wr = result.naive_yes_wins / result.resolved if result.resolved > 0 else 0.5
            alpha = dir_wr - naive_wr
        else:
            parts.append("方向信号笔数 < 5，不足以评估 alpha。")
        if alpha > 0.05:
            parts.append(f"相对基线 alpha: +{alpha:.0%}（信号可能有价值）。")
        elif alpha > -0.05:
            parts.append(f"相对基线 alpha: {alpha:+.0%}（信号和随机差不多）。")
        else:
            parts.append(f"相对基线 alpha: {alpha:+.0%}（信号可能没有超过随机的价值）。")

        if result.directional_friction_pnl > 0:
            parts.append(f"扣摩擦 PnL: +${result.directional_friction_pnl:.2f}。")
        else:
            parts.append(f"扣摩擦 PnL: ${result.directional_friction_pnl:.2f}（成本吞噬利润）。")
    else:
        parts.append("无方向性信号数据，仅基于 naive YES 策略评估。")

    # Sample size assessment (stricter thresholds)
    if result.resolved >= 50:
        parts.append(f"样本 {result.resolved} 笔，可初步参考。")
    elif result.resolved >= 20:
        parts.append(f"样本 {result.resolved} 笔，趋势可观察但不足以高度确信。")
    else:
        parts.append(f"样本仅 {result.resolved} 笔，结论可能受运气影响，不建议据此调整策略。")

    # Conservative recommendation
    if result.directional_trades >= 20 and result.directional_friction_pnl > 0 and alpha > 0.05:
        parts.append("建议：继续使用，单笔不超过账户 8%。")
    elif result.friction_adjusted_pnl > 0 and result.resolved >= 20:
        parts.append("建议：谨慎参考，信号有一定趋势但样本不够确定。")
    else:
        parts.append("建议：暂不依据信号交易，继续 paper trade 积累数据。")

    return " ".join(parts)
