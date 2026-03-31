"""Analysis store: persist per-market AI analysis versions."""

import json
from pathlib import Path

from pydantic import BaseModel


class AnalysisVersion(BaseModel):
    """A single AI analysis snapshot for a market."""

    version: int  # 1-indexed
    created_at: str  # ISO 8601
    market_title: str
    yes_price_at_analysis: float | None = None

    # Agent 1 result
    analyst_output: dict

    # Mispricing
    mispricing_signal: str = "none"
    mispricing_details: str | None = None

    # Agent 2 result
    narrative_output: dict

    # Metadata
    previous_version: int | None = None
    elapsed_seconds: float = 0.0


def load_analyses(path: str | Path) -> dict[str, list[dict]]:
    """Load all analyses. Returns {market_id: [version_dict, ...]}."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_analyses(data: dict[str, list[dict]], path: str | Path):
    """Save all analyses."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_market_analyses(market_id: str, path: str | Path) -> list[AnalysisVersion]:
    """Get all analysis versions for a market."""
    data = load_analyses(path)
    raw_list = data.get(market_id, [])
    result = []
    for v in raw_list:
        try:
            result.append(AnalysisVersion.model_validate(v))
        except Exception:
            continue
    return result


def append_analysis(market_id: str, version: AnalysisVersion, path: str | Path,
                    max_versions: int = 10):
    """Append an analysis version, truncating to max_versions per market."""
    data = load_analyses(path)
    if market_id not in data:
        data[market_id] = []
    data[market_id].append(version.model_dump())
    data[market_id] = data[market_id][-max_versions:]
    save_analyses(data, path)


def build_previous_context(existing: list[AnalysisVersion]) -> str | None:
    """Build context string from the latest analysis version for AI prompt injection."""
    if not existing:
        return None
    last = existing[-1]
    n = last.narrative_output
    return (
        f"--- 上次分析 (v{last.version}, {last.created_at[:10]}, "
        f"当时价格 YES={last.yes_price_at_analysis}) ---\n"
        f"摘要: {n.get('summary', 'N/A')}\n"
        f"风险: {', '.join(rf.get('text', str(rf)) if isinstance(rf, dict) else str(rf) for rf in n.get('risk_flags', []))}\n"
        f"结论: {n.get('one_line_verdict', 'N/A')}\n"
        f"---\n"
        f"请基于当前最新数据分析。如果情况有变化，指出和上次的不同。"
    )
