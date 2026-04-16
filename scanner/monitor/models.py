"""Movement detection models and scoring."""

from pydantic import BaseModel


class MovementSignals(BaseModel):
    """Raw signals computed from market data."""

    # Universal signals
    price_z_score: float = 0.0
    volume_ratio: float = 0.0
    book_imbalance: float = 0.0
    trade_concentration: float = 0.0
    open_interest_delta: float = 0.0

    # Crypto-specific
    fair_value_divergence: float = 0.0
    underlying_z_score: float = 0.0
    cross_divergence: float = 0.0

    # Political-specific
    sustained_drift: float = 0.0

    # Economic-specific
    time_decay_adjusted_move: float = 0.0
    correlated_asset_move: float = 0.0

    # Shared
    volume_price_confirmation: float = 0.0


class MovementResult(BaseModel):
    """Dual-dimension movement assessment."""

    magnitude: float = 0.0  # 0-100
    quality: float = 0.0    # 0-100
    signals: MovementSignals = MovementSignals()

    @property
    def label(self) -> str:
        """Classification label based on magnitude and quality."""
        m_high = self.magnitude >= 50
        q_high = self.quality >= 50
        if m_high and q_high:
            return "consensus"
        if m_high and not q_high:
            return "whale_move"
        if not m_high and q_high:
            return "slow_build"
        return "noise"

    def should_trigger(self, m_threshold: float = 70, q_threshold: float = 60) -> bool:
        """Whether this movement should trigger a full AI analysis."""
        return self.magnitude >= m_threshold and self.quality >= q_threshold

    @property
    def cooldown_seconds(self) -> int:
        """Dynamic cooldown based on magnitude.

        Must exceed AI analysis time (~15min) to prevent overlapping runs.
        """
        if self.magnitude >= 90:
            return 1200   # 20min
        if self.magnitude >= 80:
            return 1800   # 30min
        return 3600       # 60min
