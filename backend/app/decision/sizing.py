"""Position sizing (roadmap 3.4) — turn a direction into a *how much*.

A signal says BUY; this says BUY *how much*. The recommendation only becomes actionable with a size,
and a size is only honest if it widens with conviction and narrows with doubt, risk, concentration,
and a poor track record. So the sizer is a deterministic, transparent stack of multipliers on a
signal-keyed base weight — no LLM, fully auditable, every factor shown in the rationale:

    target = base(signal) × conviction × confidence × risk × concentration × calibration   (capped)

Conditioned on (per the roadmap): **conviction** (the judge's calibrated probability), **concentration**
(a correlation-with-the-book proxy: how many watchlist names already share this sector), and the
**calibration** trust-shrink from 3.3 (shrink when this archetype's stated conviction has historically
run ahead of realized success). Risk flags and data confidence gate it further. It only ever sizes a
position the decision already supports — a HOLD/REDUCE/SELL is about trimming, not adding.
"""

from dataclasses import asdict, dataclass, field

# Single-name budget. A max-conviction, clean STRONG_BUY tops out here; nothing sizes past it.
MAX_POSITION_PCT = 10.0

# Base target weight by *final* signal (the binding decision, post-gates).
_BASE_PCT = {"STRONG_BUY": 8.0, "BUY": 5.0, "HOLD": 0.0, "REDUCE": 0.0, "SELL": 0.0}

_CONF_MULT = {"high": 1.0, "moderate": 0.8, "low": 0.5}


def _conviction_mult(conviction: float | None) -> float:
    """Map the judge's conviction to a size multiplier. Below the 0.35 buy-gate the position is a
    toe-hold; unknown conviction is treated cautiously (0.6). Linear 0.35→1.0 ⇒ 0.5×→1.25×."""
    if conviction is None:
        return 0.6
    if conviction < 0.35:
        return 0.4
    # 0.35..1.0 → 0.5..1.25
    return round(0.5 + (min(conviction, 1.0) - 0.35) / 0.65 * 0.75, 3)


def _risk_mult(risk_flags: list[dict]) -> tuple[float, str | None]:
    """Critical flag ⇒ no add (0×). Each major ⇒ ×0.8, compounding. Watch flags don't size."""
    critical = sum(1 for f in risk_flags if f.get("level") == "critical")
    major = sum(1 for f in risk_flags if f.get("level") == "major")
    if critical:
        return 0.0, f"{critical} critical flag(s) → no new capital"
    if major:
        return round(0.8 ** major, 3), f"{major} major flag(s) → ×{round(0.8 ** major, 3)}"
    return 1.0, None


def _concentration_mult(sector_peers: int) -> tuple[float, str | None]:
    """Correlation-with-the-book proxy: names already in this sector on the watchlist are a coarse
    stand-in for correlation (no returns-covariance needed). Each extra same-sector name shrinks the
    add — 1/(1+0.25·(k−1)). One name in the sector (this one) ⇒ no discount."""
    k = max(sector_peers, 1)
    if k <= 1:
        return 1.0, None
    factor = round(1.0 / (1.0 + 0.25 * (k - 1)), 3)
    return factor, f"{k} watchlist names in this sector → concentration ×{factor}"


def _tier(weight_pct: float) -> str:
    if weight_pct <= 0:
        return "none"
    if weight_pct < 2.0:
        return "starter"
    if weight_pct < 5.0:
        return "half"
    if weight_pct < 8.0:
        return "full"
    return "max"


@dataclass
class SizingResult:
    action: str               # 'accumulate' | 'hold' | 'trim' | 'exit'
    target_weight_pct: float  # suggested portfolio weight for the position
    max_weight_pct: float     # the single-name cap in force
    tier: str                 # none | starter | half | full | max
    multipliers: dict = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def compute_position_size(
    final_signal: str,
    confidence: str,
    conviction: float | None,
    risk_flags: list[dict],
    sector_peers: int = 1,
    calibration_factor: float = 1.0,
    calibration_note: str | None = None,
) -> SizingResult:
    """Deterministic size guidance for the binding decision. See module docstring for the stack."""
    signal = (final_signal or "HOLD").upper()

    # Non-buys: sizing is about exiting/trimming/holding, not adding.
    if signal in {"SELL", "REDUCE", "HOLD"}:
        action = {"SELL": "exit", "REDUCE": "trim", "HOLD": "hold"}[signal]
        rationale = {
            "SELL": "Exit / do not hold — the decision is SELL.",
            "REDUCE": "Trim toward a smaller position — the decision is REDUCE.",
            "HOLD": "Hold existing; commit no new capital — the decision is HOLD.",
        }[signal]
        return SizingResult(action=action, target_weight_pct=0.0, max_weight_pct=MAX_POSITION_PCT,
                            tier="none", multipliers={}, rationale=rationale)

    # Buys: stack the multipliers.
    base = _BASE_PCT.get(signal, 0.0)
    conv_m = _conviction_mult(conviction)
    conf_m = _CONF_MULT.get(confidence, 0.8)
    risk_m, risk_note = _risk_mult(risk_flags)
    conc_m, conc_note = _concentration_mult(sector_peers)
    cal_m = max(min(calibration_factor, 1.0), 0.0)

    target = base * conv_m * conf_m * risk_m * conc_m * cal_m
    target = round(min(target, MAX_POSITION_PCT), 2)

    multipliers = {
        "base_pct": base,
        "conviction": conv_m,
        "confidence": conf_m,
        "risk": risk_m,
        "concentration": conc_m,
        "calibration": cal_m,
    }

    notes = [n for n in (risk_note, conc_note, calibration_note) if n]
    conv_txt = f"{conviction:.2f}" if conviction is not None else "n/a"
    rationale = (
        f"{signal}: base {base:.1f}% × conviction {conv_m} (judge {conv_txt}) × confidence {conf_m} "
        f"({confidence})"
        + (f" × risk {risk_m}" if risk_m != 1.0 else "")
        + (f" × concentration {conc_m}" if conc_m != 1.0 else "")
        + (f" × calibration {cal_m}" if cal_m != 1.0 else "")
        + f" → {target:.2f}% (cap {MAX_POSITION_PCT:.0f}%)."
    )
    if notes:
        rationale += " " + " ".join(notes)

    action = "accumulate" if target > 0 else "hold"
    return SizingResult(action=action, target_weight_pct=target, max_weight_pct=MAX_POSITION_PCT,
                        tier=_tier(target), multipliers=multipliers, rationale=rationale[:800])
