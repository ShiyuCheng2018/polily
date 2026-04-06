"""Lightweight price poller: fetches data and computes movement signals.

Zero AI cost — only math. Triggers analyze_market() when thresholds are exceeded.
"""

import logging
from datetime import UTC, datetime

from scanner.api import PolymarketClient
from scanner.config import ScannerConfig
from scanner.db import PolilyDB
from scanner.movement import MovementResult, MovementSignals
from scanner.movement_scorer import compute_movement_score
from scanner.movement_signals import (
    compute_book_imbalance,
    compute_price_z_score,
    compute_sustained_drift,
    compute_time_decay_adjusted_move,
    compute_trade_concentration,
    compute_volume_price_confirmation,
    compute_volume_ratio,
)
from scanner.movement_store import (
    append_movement,
    get_recent_movements,
    get_today_analysis_count,
)

logger = logging.getLogger(__name__)


class PricePoller:
    """Polls market data and computes movement scores."""

    def __init__(self, config: ScannerConfig, db: PolilyDB,
                 client: PolymarketClient | None = None):
        self.config = config
        self.db = db
        self._client = client  # reuse across polls if provided
        self._owns_client = client is None

    async def _get_client(self) -> PolymarketClient:
        if self._client is None:
            self._client = PolymarketClient(self.config.api)
            self._owns_client = True
        return self._client

    async def close(self):
        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None

    async def _fetch_market_data(self, token_id: str, condition_id: str = "") -> dict:
        """Fetch current price, orderbook, and recent trades."""
        client = await self._get_client()
        bids, asks = await client.fetch_book(token_id)

        # Trades from Data API (public, uses condition_id)
        trades = await client.fetch_trades(condition_id, limit=100)

        yes_price = None
        if bids and asks:
            yes_price = (bids[0].price + asks[0].price) / 2

        return {
            "yes_price": yes_price,
            "bids": bids,
            "asks": asks,
            "trades": trades,
        }

    def _build_price_history(self, market_id: str, hours: int = 6) -> list[float]:
        """Build price history from movement_log for z-score calculation."""
        entries = get_recent_movements(market_id, self.db, hours=hours)
        prices = [e["yes_price"] for e in reversed(entries) if e.get("yes_price")]
        return prices

    def _compute_baseline_volume(self, market_id: str, hours: int = 6) -> float:
        """Compute average trade volume per poll window from movement_log."""
        entries = get_recent_movements(market_id, self.db, hours=hours)
        if not entries:
            return 0.0
        volumes = [e.get("trade_volume", 0) for e in entries]
        if not volumes:
            return 0.0
        return sum(volumes) / len(volumes)

    async def poll_single(
        self,
        market_id: str,
        *,
        market_type: str = "other",
        token_id: str,
        condition_id: str = "",
        prev_price: float | None = None,
        market_title: str = "",
        days_to_resolution: float = 7.0,
    ) -> MovementResult:
        """Poll a single market and compute movement score."""
        data = await self._fetch_market_data(token_id, condition_id=condition_id)
        current_price = data.get("yes_price") or 0.0

        price_history = self._build_price_history(market_id)

        bids = data.get("bids", [])
        asks = data.get("asks", [])
        bid_depth = sum(b.size for b in bids)
        ask_depth = sum(a.size for a in asks)
        spread = (asks[0].price - bids[0].price) if bids and asks else None

        trades = data.get("trades", [])
        trade_sizes = [t.size for t in trades] if trades else []
        recent_volume = sum(trade_sizes)
        baseline_volume = self._compute_baseline_volume(market_id)

        price_change_pct = 0.0
        if prev_price and prev_price > 0:
            price_change_pct = (current_price - prev_price) / prev_price

        vol_ratio = compute_volume_ratio(recent_volume, baseline_volume)

        signals = MovementSignals(
            price_z_score=compute_price_z_score(current_price, price_history),
            volume_ratio=vol_ratio,
            book_imbalance=compute_book_imbalance(bid_depth, ask_depth),
            trade_concentration=compute_trade_concentration(trade_sizes),
            volume_price_confirmation=compute_volume_price_confirmation(
                price_change_pct, vol_ratio
            ),
        )

        # Market-type-specific enrichment
        if market_type == "crypto" and market_title:
            crypto_data = await self._fetch_crypto_signals(
                market_title, current_price, prev_price,
                days_to_resolution=days_to_resolution,
            )
            signals.fair_value_divergence = crypto_data.get("fair_value_divergence", 0.0)
            signals.underlying_z_score = crypto_data.get("underlying_z_score", 0.0)
            signals.cross_divergence = crypto_data.get("cross_divergence", 0.0)

        elif market_type == "political":
            # sustained_drift from price history
            if len(price_history) >= 3:
                signals.sustained_drift = compute_sustained_drift(price_history)

        elif market_type == "economic_data":
            # time_decay_adjusted_move based on proximity to resolution
            if price_change_pct != 0 and days_to_resolution > 0:
                signals.time_decay_adjusted_move = compute_time_decay_adjusted_move(
                    price_change_pct, days_to_resolution
                )

        result = compute_movement_score(signals, market_type, self.config.movement)

        append_movement(
            market_id, result,
            yes_price=current_price,
            prev_yes_price=prev_price,
            trade_volume=recent_volume,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            spread=spread,
            db=self.db,
        )

        return result

    async def _fetch_crypto_signals(self, market_title: str, current_odds: float,
                                     prev_odds: float | None,
                                     days_to_resolution: float = 7.0) -> dict:
        """Fetch crypto-specific signals from Binance via CCXT."""
        from scanner.mispricing import compute_crypto_fair_value
        from scanner.price_feeds import BinancePriceFeed, extract_crypto_asset

        feed = BinancePriceFeed()
        try:
            params = await feed.get_crypto_params(market_title)
            if not params:
                return {}

            current_underlying = params["current_underlying_price"]
            threshold = params["threshold_price"]
            vol = params["annual_volatility"]

            symbol = extract_crypto_asset(market_title)
            if not symbol:
                return {}

            prices_1h = await feed.get_short_term_prices(symbol, "1h", limit=24)

            from scanner.movement_signals import (
                compute_cross_divergence,
                compute_fair_value_divergence,
                compute_underlying_z_score,
            )

            underlying_z = compute_underlying_z_score(current_underlying, prices_1h)

            odds_change = 0.0
            if prev_odds and prev_odds > 0:
                odds_change = (current_odds - prev_odds) / prev_odds

            underlying_change = 0.0
            if len(prices_1h) >= 2 and prices_1h[-2] > 0:
                underlying_change = (current_underlying - prices_1h[-2]) / prices_1h[-2]

            cross_div = compute_cross_divergence(underlying_change, odds_change)

            import contextlib
            fair_val = current_odds  # fallback
            with contextlib.suppress(Exception):
                fair_val = compute_crypto_fair_value(current_underlying, threshold, days_to_resolution, vol)

            fv_div = compute_fair_value_divergence(current_odds, fair_val)

            return {
                "fair_value_divergence": fv_div,
                "underlying_z_score": underlying_z,
                "cross_divergence": cross_div,
            }
        finally:
            await feed.close()

    def check_cooldown(self, market_id: str, cooldown_seconds: int = 1800) -> bool:
        """Check if market is in cooldown period.

        Returns True if still in cooldown (should NOT trigger analysis).
        """
        entries = get_recent_movements(market_id, self.db, hours=1)
        for e in entries:
            if e.get("triggered_analysis"):
                triggered_at = datetime.fromisoformat(e["created_at"])
                if triggered_at.tzinfo is None:
                    triggered_at = triggered_at.replace(tzinfo=UTC)
                elapsed = (datetime.now(UTC) - triggered_at).total_seconds()
                if elapsed < cooldown_seconds:
                    return True
        return False

    def check_daily_limit(self, market_id: str) -> bool:
        """Check if market has exceeded daily analysis limit.

        Returns True if limit exceeded (should NOT trigger analysis).
        """
        count = get_today_analysis_count(market_id, self.db)
        return count >= self.config.movement.daily_analysis_limit
