"""Market data models for Polymarket scanner."""

from datetime import datetime

from pydantic import BaseModel, computed_field


class BookLevel(BaseModel):
    """Single level in an order book (price + size in USD)."""

    price: float
    size: float


class Trade(BaseModel):
    """A single trade from CLOB API."""

    id: str = ""
    price: float
    size: float
    side: str  # "BUY" or "SELL"
    timestamp: str = ""


class Market(BaseModel):
    """Normalized market model with computed fields."""

    # Identity
    market_id: str
    event_id: str | None = None
    event_slug: str | None = None
    market_slug: str | None = None
    title: str
    description: str | None = None
    rules: str | None = None
    resolution_source: str | None = None
    category: str | None = None
    market_type: str | None = None
    tags: list[str] = []
    outcomes: list[str]

    # Prices
    yes_price: float | None = None
    no_price: float | None = None
    best_bid_yes: float | None = None
    best_ask_yes: float | None = None
    best_bid_no: float | None = None
    best_ask_no: float | None = None
    spread_yes: float | None = None
    spread_no: float | None = None

    # Volume & interest
    volume: float | None = None
    open_interest: float | None = None

    # Time
    resolution_time: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    data_fetched_at: datetime

    # Token IDs for CLOB API (parsed from Gamma clobTokenIds JSON string)
    clob_token_id_yes: str | None = None
    clob_token_id_no: str | None = None
    condition_id: str | None = None

    # Multi-outcome support (new in v0.5.0)
    group_item_title: str | None = None      # display label in multi-outcome ("No Prison Time", ">86k")
    group_item_threshold: str | None = None   # display order index ("0","1","2"...)
    question_id: str | None = None            # hex hash, different from condition_id
    neg_risk: bool = False                     # part of neg_risk event
    neg_risk_request_id: str | None = None    # unique per market within neg_risk group
    neg_risk_other: bool = False               # catch-all "Other" outcome
    accepting_orders: bool = True              # whether orderbook is active

    # Fee schedule (Gamma `feesEnabled` + `feeSchedule.rate`)
    fees_enabled: bool = False
    fee_rate: float | None = None

    # Order book depth
    book_depth_bids: list[BookLevel] | None = None
    book_depth_asks: list[BookLevel] | None = None

    # Multi-outcome consistency
    event_outcome_prices_sum: float | None = None

    # --- Computed fields ---

    @computed_field
    @property
    def mid_price_yes(self) -> float | None:
        if self.best_bid_yes is not None and self.best_ask_yes is not None:
            return (self.best_bid_yes + self.best_ask_yes) / 2
        return None

    @computed_field
    @property
    def spread_pct_yes(self) -> float | None:
        mid = self.mid_price_yes
        if mid is not None and mid > 0 and self.best_bid_yes is not None and self.best_ask_yes is not None:
            return (self.best_ask_yes - self.best_bid_yes) / mid
        return None

    @computed_field
    @property
    def spread_pct_best_side(self) -> float | None:
        """Spread % on the cheaper-to-trade side (YES or NO).

        Same absolute spread on both sides of a binary market, but the % cost
        is `spread_abs / mid_side`. For a 25¢ YES / 75¢ NO market with a 1¢
        spread, YES costs 4% while NO costs 1.3%. Scoring and filter logic
        should reflect the side a rational trader would actually use.

        Formula: `spread_abs / max(mid_yes, mid_no)`.
        """
        if (
            self.best_bid_yes is None
            or self.best_ask_yes is None
            or self.mid_price_yes is None
        ):
            return None
        spread_abs = self.best_ask_yes - self.best_bid_yes
        mid_yes = self.mid_price_yes
        best_mid = max(mid_yes, 1 - mid_yes)
        if best_mid <= 0:
            return None
        return spread_abs / best_mid

    @computed_field
    @property
    def days_to_resolution(self) -> float | None:
        if self.resolution_time is None:
            return None
        delta = self.resolution_time - self.data_fetched_at
        return delta.total_seconds() / 86400

    @computed_field
    @property
    def hours_to_resolution(self) -> float | None:
        if self.days_to_resolution is not None:
            return self.days_to_resolution * 24
        return None

    @computed_field
    @property
    def is_binary(self) -> bool:
        return len(self.outcomes) == 2

    @computed_field
    @property
    def is_extreme_probability(self) -> bool:
        if self.yes_price is None:
            return False
        return self.yes_price < 0.15 or self.yes_price > 0.85

    @computed_field
    @property
    def is_mid_probability(self) -> bool:
        if self.yes_price is None:
            return False
        return 0.30 <= self.yes_price <= 0.70

    @computed_field
    @property
    def round_trip_friction_pct(self) -> float | None:
        """Round-trip cost on the *best-side-to-trade*.

        The absolute $0.01 spread means very different percentages on a 25¢
        YES vs a 75¢ YES market — same book, but buying NO at 76¢ has ~1.3%
        cost while buying YES at 25¢ has ~4% cost. A single market-level
        friction number should reflect the side a rational trader would
        actually use, so we take the cheaper side.

        Formula: 2 × spread_abs / max(mid_yes, mid_no).
        """
        if (
            self.best_bid_yes is None
            or self.best_ask_yes is None
            or self.mid_price_yes is None
            or self.mid_price_yes <= 0
        ):
            return None
        spread_abs = self.best_ask_yes - self.best_bid_yes
        mid_yes = self.mid_price_yes
        mid_no = 1 - mid_yes
        best_side_mid = max(mid_yes, mid_no)
        if best_side_mid <= 0:
            return None
        return (spread_abs / best_side_mid) * 2

    @computed_field
    @property
    def total_bid_depth_usd(self) -> float | None:
        if self.book_depth_bids is None:
            return None
        return sum(level.size for level in self.book_depth_bids)

    @computed_field
    @property
    def total_ask_depth_usd(self) -> float | None:
        if self.book_depth_asks is None:
            return None
        return sum(level.size for level in self.book_depth_asks)

    @computed_field
    @property
    def vamp(self) -> float | None:
        """Volume-Adjusted Mid Price — more accurate than simple mid in imbalanced books."""
        bid = self.best_bid_yes
        ask = self.best_ask_yes
        bd = self.total_bid_depth_usd
        ad = self.total_ask_depth_usd
        if bid is not None and ask is not None and bd and ad and (bd + ad) > 0:
            return (bid * ad + ask * bd) / (bd + ad)
        return self.mid_price_yes

    @computed_field
    @property
    def order_book_imbalance(self) -> float | None:
        """OBI: (bid_depth - ask_depth) / (bid_depth + ask_depth). Range -1 to +1."""
        bd = self.total_bid_depth_usd
        ad = self.total_ask_depth_usd
        if bd is not None and ad is not None and (bd + ad) > 0:
            return (bd - ad) / (bd + ad)
        return None

    @computed_field
    @property
    def slippage_20usd(self) -> float | None:
        """Estimated slippage for a $20 market order: order_size / (2 * depth)."""
        bd = self.total_bid_depth_usd
        if bd and bd > 0:
            return 20.0 / (2 * bd)
        return None

    @computed_field
    @property
    def polymarket_url(self) -> str:
        if self.event_slug:
            if self.market_slug:
                return f"https://polymarket.com/event/{self.event_slug}/{self.market_slug}"
            return f"https://polymarket.com/event/{self.event_slug}"
        return f"https://polymarket.com/event/{self.market_id}"
