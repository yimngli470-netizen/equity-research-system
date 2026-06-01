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


# ── Archetype-conditioned weight profiles (roadmap 1.4) ──────────────────────────
#
# One ruler doesn't fit every business model: momentum at a cyclical's peak is a trap, spot
# multiples mislead for commodities, and a compounder's thesis is margins + not overpaying.
# Each profile re-weights the SAME seven categories for a business-model archetype (from 1.1).
# Documented priors now; a learned model later once the backtest panel exists (§4a M6).
#
# Cycle-position / normalized-earnings is its own future signal (Phase 2.2 / ML M3); until it
# exists, "cyclicals ↑ cycle-position" is expressed by leaning on `event` (earnings quality,
# guidance, surprise — where the cycle inflection shows) and `risk`, and leaning OFF spot
# `valuation` multiples and `momentum`. Each profile sums to 1.0.
ARCHETYPE_WEIGHTS: dict[str, ScoringWeights] = {
    # Thesis = where in the cycle. Spot multiples mislead at peak/trough; peak momentum is a trap;
    # and an earnings BEAT at the peak is a warning, not a positive — so `event` is NOT upweighted.
    # Lean on risk (downside) and profitability (margin direction is the best cycle proxy we have
    # until Phase 2.2 adds a real cycle-position signal).
    "cyclical-commodity": ScoringWeights(
        growth=0.15, profitability=0.20, valuation=0.12,
        momentum=0.05, sentiment=0.08, risk=0.25, event=0.15,
    ),
    # Thesis = durable above-market growth. Lean into growth; tolerate rich multiples.
    "secular-grower": ScoringWeights(
        growth=0.30, profitability=0.12, valuation=0.13,
        momentum=0.12, sentiment=0.08, risk=0.10, event=0.15,
    ),
    # Thesis = moat + durable high-margin economics. Profitability and growth durability lead.
    "platform": ScoringWeights(
        growth=0.18, profitability=0.22, valuation=0.18,
        momentum=0.08, sentiment=0.08, risk=0.11, event=0.15,
    ),
    # Thesis = steady compounding without overpaying. Margins + valuation discipline; low momentum.
    "mature-compounder": ScoringWeights(
        growth=0.12, profitability=0.25, valuation=0.22,
        momentum=0.06, sentiment=0.08, risk=0.12, event=0.15,
    ),
    # Balance-sheet-driven: valuation (book), credit risk, returns lead; growth/momentum matter less.
    "financial": ScoringWeights(
        growth=0.10, profitability=0.20, valuation=0.22,
        momentum=0.08, sentiment=0.08, risk=0.17, event=0.15,
    ),
    # Thesis = cheapness + survival + an earnings inflection. Valuation and risk lead.
    "deep-value-turnaround": ScoringWeights(
        growth=0.10, profitability=0.13, valuation=0.27,
        momentum=0.07, sentiment=0.08, risk=0.20, event=0.15,
    ),
}


def weights_for_archetype(archetype: str | None) -> ScoringWeights:
    """Select the weight profile for an archetype, falling back to DEFAULT_WEIGHTS."""
    if archetype is None:
        return DEFAULT_WEIGHTS
    return ARCHETYPE_WEIGHTS.get(archetype, DEFAULT_WEIGHTS)
