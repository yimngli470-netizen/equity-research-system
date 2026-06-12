"""Forecast compiler (roadmap 4.2) — pure arithmetic from assumptions to EPS path.

The LLM sets the assumption paths ONCE (with cited basis); this module turns them into quarterly
projections deterministically, so two runs with the same assumptions produce byte-identical numbers
(§4a). Revenue is YoY-anchored — forward quarter i grows vs the ACTUAL quarter 4 back (i ≤ 4) or
the already-forecast quarter 4 back (i ≥ 5) — which carries seasonality through for free.

    revenue_i = base_{i-4} × (1 + yoy_i)
    op_income_i = revenue_i × (gm_i − opex_i)
    net_income_i = op_income_i × net_factor
    shares_i = shares_0 × (1 + share_change_qoq)^i
    eps_i = net_income_i / shares_i
"""

import calendar
from dataclasses import dataclass
from datetime import date

HORIZON = 8

# Hygiene clamps (the P8 lesson: every LLM-emitted number gets bounds enforced in code).
_CLAMPS = {
    "revenue_yoy": (-0.90, 3.00),
    "gross_margin": (0.0, 1.0),
    "opex_ratio": (0.0, 1.0),
    "net_factor": (0.0, 1.5),
    "share_change_qoq": (-0.05, 0.05),
}


def _clamp(v: float, key: str) -> float:
    lo, hi = _CLAMPS[key]
    return max(lo, min(hi, float(v)))


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


@dataclass
class ScenarioPath:
    """One scenario's assumption paths, post-hygiene. Arrays are length HORIZON."""
    revenue_yoy: list[float]
    gross_margin: list[float]
    opex_ratio: list[float]
    net_factor: float
    share_change_qoq: float
    rationale: str = ""

    @classmethod
    def from_llm(cls, raw: dict, defaults: dict) -> "ScenarioPath":
        """Parse + clamp one scenario from the LLM payload; pad/truncate paths to HORIZON.
        Missing values fall back to the driver-history medians (`defaults`)."""
        def path(key: str, default: float | None) -> list[float]:
            xs = raw.get(key) or []
            xs = [x for x in xs if isinstance(x, (int, float))]
            if not xs:
                xs = [default if default is not None else 0.0]
            xs = (xs + [xs[-1]] * HORIZON)[:HORIZON]
            clamp_key = {"revenue_yoy_path": "revenue_yoy",
                         "gross_margin_path": "gross_margin",
                         "opex_ratio_path": "opex_ratio"}[key]
            return [_clamp(x, clamp_key) for x in xs]

        nf = raw.get("net_factor")
        nf = _clamp(nf, "net_factor") if isinstance(nf, (int, float)) else (defaults.get("net_factor") or 0.8)
        sc = raw.get("share_change_qoq")
        sc = _clamp(sc, "share_change_qoq") if isinstance(sc, (int, float)) else 0.0
        return cls(
            revenue_yoy=path("revenue_yoy_path", defaults.get("revenue_yoy")),
            gross_margin=path("gross_margin_path", defaults.get("gross_margin")),
            opex_ratio=path("opex_ratio_path", defaults.get("opex_ratio")),
            net_factor=nf,
            share_change_qoq=sc,
            rationale=str(raw.get("rationale") or "")[:1500],
        )


def compile_scenario(
    path: ScenarioPath,
    actual_revenue_last4: list[float],   # chronological: [q-3, q-2, q-1, q0]
    latest_end: date,
    shares_0: float,
) -> list[dict]:
    """Quarterly projections for one scenario. Deterministic; see module docstring."""
    revenues: list[float] = []
    out: list[dict] = []
    for i in range(HORIZON):
        base = actual_revenue_last4[i] if i < 4 else revenues[i - 4]
        rev = base * (1.0 + path.revenue_yoy[i])
        gm, opx = path.gross_margin[i], path.opex_ratio[i]
        oi = rev * (gm - opx)
        ni = oi * path.net_factor
        shares = shares_0 * (1.0 + path.share_change_qoq) ** (i + 1)
        eps = (ni / shares) if shares else None
        end = _add_months(latest_end, 3 * (i + 1))
        revenues.append(rev)
        out.append({
            "q": i + 1,
            "end_approx": end.isoformat(),
            "revenue": round(rev, 0),
            "revenue_yoy": round(path.revenue_yoy[i], 4),
            "gross_margin": round(gm, 4),
            "operating_income": round(oi, 0),
            "net_income": round(ni, 0),
            "eps": round(eps, 3) if eps is not None else None,
            "shares": round(shares, 0),
        })
    return out


def aggregate(projections: list[dict]) -> dict:
    """NTM (q1-4) and the following year (q5-8) sums."""
    def s(rows, key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals), 3) if len(vals) == len(rows) else None
    return {
        "ntm_eps": s(projections[:4], "eps"),
        "ntm_revenue": s(projections[:4], "revenue"),
        "next_year_eps": s(projections[4:8], "eps"),
        "next_year_revenue": s(projections[4:8], "revenue"),
    }
