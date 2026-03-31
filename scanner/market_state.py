"""Market state persistence — PASS/WATCH/ACTIVE status per market."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from scanner.agents.schemas import WatchCondition


class MarketState(BaseModel):
    """User's decision state for a market."""

    status: Literal["pass", "watch", "active"]
    updated_at: str  # ISO 8601
    watch_conditions: WatchCondition | None = None
    notes: str = ""


def load_market_states(path: str | Path) -> dict[str, MarketState]:
    """Load all market states."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            data = json.load(f)
        return {mid: MarketState.model_validate(state) for mid, state in data.items()}
    except (json.JSONDecodeError, ValueError):
        return {}


def save_market_states(states: dict[str, MarketState], path: str | Path):
    """Save all market states."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump({mid: s.model_dump() for mid, s in states.items()}, f, indent=2, ensure_ascii=False)


def set_market_state(market_id: str, state: MarketState, path: str | Path):
    """Set state for a single market."""
    states = load_market_states(path)
    states[market_id] = state
    save_market_states(states, path)


def get_market_state(market_id: str, path: str | Path) -> MarketState | None:
    """Get state for a single market."""
    states = load_market_states(path)
    return states.get(market_id)


def is_passed(market_id: str, path: str | Path) -> bool:
    """Check if a market is marked as PASS."""
    state = get_market_state(market_id, path)
    return state is not None and state.status == "pass"


def get_watched_markets(path: str | Path) -> dict[str, MarketState]:
    """Get all markets with status=watch."""
    states = load_market_states(path)
    return {mid: s for mid, s in states.items() if s.status == "watch"}
