"""Position sizing (roadmap 3.4) — turn a direction into a *how much*.

A signal says BUY; this says BUY *how much*. The recommendation only becomes actionable with a size,
and a size is only honest if it widens with conviction and narrows with doubt, risk, concentration,
and a poor track record. So the sizer is a deterministic, transparent stack of multipliers on a
signal-keyed base weight — no LLM, fully auditable, every factor shown in the rationale:

    target = base(signal) × conviction × confidence × risk × concentration × calibration   (capped)

Conditioned on (per the roadmap): **conviction** (the judge's calibrated probability), **concentration**
(from the REAL book, 6.2: how much of total capital already sits in this name's sector, and how
correlated the name is with the rest of the holdings), and the **calibration** trust-shrink from 3.3
(shrink when this archetype's stated conviction has historically run ahead of realized success). Risk
flags and data confidence gate it further. It only ever sizes a position the decision already supports.

The output is target-vs-CURRENT: given what you actually hold (6.2), it reports the delta — "add 2%"
or "trim 1.5%" — not just an abstract target. Until a portfolio is entered the book is empty, so
concentration is neutral and the current weight is 0 (the target IS the add).
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


def _concentration_mult(sector_weight: float, corr_with_book: float | None) -> tuple[float, str | None]:
    """Concentration discount from the REAL book (6.2). Two overlapping risks, blended:
      • SECTOR weight — the share of total capital already in this name's sector. 1/(1+w): an empty
        sleeve ⇒ no discount; a book already 50% in the sector ⇒ ×0.67.
      • CORRELATION with the rest of the book — a name that co-moves with what you own adds risk, not
        diversification: ×(1 − 0.2·max(corr,0)). A negative-correlation diversifier gets no penalty.
    Empty/unknown book ⇒ neutral (1.0)."""
    sector_factor = 1.0 / (1.0 + max(sector_weight, 0.0))
    corr_factor = 1.0 - 0.2 * max(corr_with_book or 0.0, 0.0)
    factor = round(sector_factor * corr_factor, 3)
    if factor >= 0.999:
        return 1.0, None
    bits = []
    if sector_weight > 0.001:
        bits.append(f"book {sector_weight * 100:.0f}% in-sector")
    if corr_with_book is not None and corr_with_book > 0.05:
        bits.append(f"corr-with-book {corr_with_book:+.2f}")
    note = f"concentration ×{factor}" + (f" ({', '.join(bits)})" if bits else "")
    return factor, note


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
    target_weight_pct: float  # recommended TOTAL portfolio weight for the position
    current_weight_pct: float # what you hold today (0 if no position / no book)
    delta_pct: float          # target − current: +add / −trim
    max_weight_pct: float     # the single-name cap in force
    tier: str                 # none | starter | half | full | max
    multipliers: dict = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _delta_phrase(delta: float, current: float) -> str:
    """Human action against the current holding: 'add 2.0%', 'trim 1.5%', or 'hold 3.0%'."""
    if delta > 0.25:
        return f"add {delta:.1f}%"
    if delta < -0.25:
        return f"trim {abs(delta):.1f}%"
    return f"hold {current:.1f}%" if current > 0.05 else "no position"


def compute_position_size(
    final_signal: str,
    confidence: str,
    conviction: float | None,
    risk_flags: list[dict],
    sector_weight: float = 0.0,
    corr_with_book: float | None = None,
    current_weight_pct: float = 0.0,
    calibration_factor: float = 1.0,
    calibration_note: str | None = None,
) -> SizingResult:
    """Deterministic size guidance for the binding decision. See module docstring for the stack.

    `sector_weight`/`corr_with_book`/`current_weight_pct` come from the real book (6.2); all default
    to the empty-book case (no concentration, no holding) so this works before a portfolio exists.
    """
    signal = (final_signal or "HOLD").upper()
    cur = round(max(current_weight_pct, 0.0), 2)

    # Non-buys: trim/exit/hold the EXISTING position (target is relative to what's held).
    if signal in {"SELL", "REDUCE", "HOLD"}:
        target = {"SELL": 0.0, "REDUCE": round(cur * 0.5, 2), "HOLD": cur}[signal]
        action = {"SELL": "exit", "REDUCE": "trim", "HOLD": "hold"}[signal]
        delta = round(target - cur, 2)
        base_txt = {
            "SELL": "Exit — the decision is SELL.",
            "REDUCE": "Trim toward a smaller position — the decision is REDUCE.",
            "HOLD": "Hold existing; commit no new capital — the decision is HOLD.",
        }[signal]
        rationale = f"{base_txt} {_delta_phrase(delta, cur)}" + (f" (hold {cur:.1f}%)." if cur > 0.05 else ".")
        return SizingResult(action=action, target_weight_pct=target, current_weight_pct=cur,
                            delta_pct=delta, max_weight_pct=MAX_POSITION_PCT,
                            tier=_tier(target), multipliers={}, rationale=rationale)

    # Buys: stack the multipliers into a target TOTAL weight, then diff against what's held.
    base = _BASE_PCT.get(signal, 0.0)
    conv_m = _conviction_mult(conviction)
    conf_m = _CONF_MULT.get(confidence, 0.8)
    risk_m, risk_note = _risk_mult(risk_flags)
    conc_m, conc_note = _concentration_mult(sector_weight, corr_with_book)
    cal_m = max(min(calibration_factor, 1.0), 0.0)

    target = base * conv_m * conf_m * risk_m * conc_m * cal_m
    target = round(min(target, MAX_POSITION_PCT), 2)
    delta = round(target - cur, 2)

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
        + f" → target {target:.2f}% (cap {MAX_POSITION_PCT:.0f}%); {_delta_phrase(delta, cur)}"
        + (f" from {cur:.1f}%." if cur > 0.05 else ".")
    )
    if notes:
        rationale += " " + " ".join(notes)

    # A BUY thesis can still mean TRIM if you're overweight vs the target the thesis supports.
    action = "accumulate" if delta > 0.25 else "trim" if delta < -0.25 else "hold"
    return SizingResult(action=action, target_weight_pct=target, current_weight_pct=cur,
                        delta_pct=delta, max_weight_pct=MAX_POSITION_PCT,
                        tier=_tier(target), multipliers=multipliers, rationale=rationale[:800])
