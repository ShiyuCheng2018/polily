"""Market data models for Polymarket scanner."""

from datetime import datetime

from pydantic import BaseModel, computed_field


class BookLevel(BaseModel):
    """Single level in an order book (price + size in USD)."""

    price: float
    size: float


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
        spc = self.spread_pct_yes
        if spc is not None:
            return spc * 2  # buy spread + sell spread estimate
        return None

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
    def polymarket_url(self) -> str:
        if self.event_slug:
            if self.market_slug:
                return f"https://polymarket.com/event/{self.event_slug}/{self.market_slug}"
            return f"https://polymarket.com/event/{self.event_slug}"
        return f"https://polymarket.com/event/{self.market_id}"
