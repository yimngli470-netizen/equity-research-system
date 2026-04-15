"""Configurable scoring weights.

Category weights determine how much each dimension contributes
to the composite score. They must sum to 1.0.

Signal thresholds determine the composite score cutoffs for
generating buy/hold/sell signals.
"""

from dataclasses import dataclass, field


@dataclass
class ScoringWeights:
    """Weights for each scoring category. Must sum to 1.0."""

    growth: float = 0.20
    profitability: float = 0.15
    valuation: float = 0.20
    momentum: float = 0.10
    sentiment: float = 0.10
    risk: float = 0.10
    event: float = 0.15

    def as_dict(self) -> dict[str, float]:
        return {
            "growth": self.growth,
            "profitability": self.profitability,
            "valuation": self.valuation,
            "momentum": self.momentum,
            "sentiment": self.sentiment,
            "risk": self.risk,
            "event": self.event,
        }

    def validate(self) -> bool:
        total = sum(self.as_dict().values())
        return abs(total - 1.0) < 0.001


@dataclass
class SignalThresholds:
    """Composite score thresholds for signal generation."""

    strong_buy: float = 0.75   # >= this → STRONG_BUY
    buy: float = 0.60          # >= this → BUY
    hold_upper: float = 0.45   # >= this → HOLD
    reduce: float = 0.30       # >= this → REDUCE
    # < reduce → SELL


def score_to_signal(composite: float, thresholds: SignalThresholds | None = None) -> str:
    """Convert a composite score (0-1) to a signal string."""
    t = thresholds or SignalThresholds()

    if composite >= t.strong_buy:
        return "STRONG_BUY"
    elif composite >= t.buy:
        return "BUY"
    elif composite >= t.hold_upper:
        return "HOLD"
    elif composite >= t.reduce:
        return "REDUCE"
    else:
        return "SELL"


# Default instances
DEFAULT_WEIGHTS = ScoringWeights()
DEFAULT_THRESHOLDS = SignalThresholds()
