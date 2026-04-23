"""Toggle auto_monitor: event-level monitoring control."""
import json
import logging

from polily.core.db import PolilyDB
from polily.core.event_store import get_event, get_event_markets
from polily.core.monitor_store import upsert_event_monitor

logger = logging.getLogger(__name__)


def toggle_auto_monitor(
    event_id: str,
    *,
    enable: bool,
    db: PolilyDB,
) -> None:
    """Enable or disable monitoring for an event.

    When enabling: records price snapshot of all sub-markets.
    When disabling: sets auto_monitor=0 (check_job cancellation is caller's responsibility).
    """
    event = get_event(event_id, db)
    if not event:
        logger.warning("Cannot toggle auto_monitor: event %s not found", event_id)
        return

    if enable:
        # Build price snapshot from current market prices
        markets = get_event_markets(event_id, db)
        snapshot = {
            m.market_id: {
                "yes": m.yes_price,
                "no": m.no_price,
                "bid": m.best_bid,
                "ask": m.best_ask,
            }
            for m in markets if not m.closed
        }
        upsert_event_monitor(
            event_id, auto_monitor=True,
            price_snapshot=json.dumps(snapshot),
            db=db,
        )
        logger.info("Enabled auto_monitor for event %s", event_id)
    else:
        upsert_event_monitor(event_id, auto_monitor=False, db=db)
        logger.info("Disabled auto_monitor for event %s", event_id)
