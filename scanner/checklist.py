"""Research checklist: load market-type-specific checklist templates."""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CHECKLISTS_DIR = Path(__file__).parent.parent / "data" / "checklists"


def load_checklist(market_type: str, checklists_dir: Path | None = None) -> list[str]:
    """Load research checklist steps for a given market type.

    Falls back to default.yaml if no type-specific template exists.
    """
    d = checklists_dir or CHECKLISTS_DIR
    path = d / f"{market_type}.yaml"
    if not path.exists():
        path = d / "default.yaml"
    if not path.exists():
        logger.warning("No checklist found at %s", path)
        return ["Read resolution rules on Polymarket", "Check recent price movement", "Ask: what edge do I have?"]
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        return data.get("steps", [])
    except Exception as e:
        logger.warning("Failed to load checklist %s: %s", path, e)
        return []
