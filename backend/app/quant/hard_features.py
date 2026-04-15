"""Hard quant features — derived from financial data, valuation multiples, and price momentum.

Each function returns a dict of {feature_name: raw_value} for a single ticker.
Normalization to 0-1 happens in the normalizer module.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.computed_metrics import ComputedSnapshot, get_computed_metrics


def _safe(val: float | None, default: float = 0.0) -> float:
    """Return val if not None, else default."""
    return val if val is not None else default


def extract_growth_features(snapshot: ComputedSnapshot) -> dict[str, float | None]:
    """Growth features from quarterly financials."""
    features: dict[str, float | None] = {}

    if not snapshot.quarters:
        return features

    latest = snapshot.quarters[0]

    # YoY growth rates (most important for growth assessment)
    features["revenue_yoy"] = latest.revenue_yoy
    features["net_income_yoy"] = latest.net_income_yoy
    features["eps_yoy"] = latest.eps_yoy
    features["operating_income_yoy"] = latest.operating_income_yoy
    features["gross_profit_yoy"] = latest.gross_profit_yoy

    # QoQ growth rates (sequential momentum)
    features["revenue_qoq"] = latest.revenue_qoq
    features["eps_qoq"] = latest.eps_qoq

    # Growth consistency — count how many of last 4 quarters had positive YoY revenue growth
    positive_quarters = 0
    total_quarters = 0
    for q in snapshot.quarters[:4]:
        if q.revenue_yoy is not None:
            total_quarters += 1
            if q.revenue_yoy > 0:
                positive_quarters += 1
    features["growth_consistency"] = (
        positive_quarters / total_quarters if total_quarters > 0 else None
    )

    # Revenue acceleration: is YoY growth improving vs prior quarter?
    if len(snapshot.quarters) >= 2:
        curr_yoy = snapshot.quarters[0].revenue_yoy
        prev_yoy = snapshot.quarters[1].revenue_yoy
        if curr_yoy is not None and prev_yoy is not None:
            features["revenue_acceleration"] = curr_yoy - prev_yoy
        else:
            features["revenue_acceleration"] = None
    else:
        features["revenue_acceleration"] = None

    return features


def extract_profitability_features(snapshot: ComputedSnapshot) -> dict[str, float | None]:
    """Profitability features from margins and efficiency metrics."""
    features: dict[str, float | None] = {}

    if not snapshot.quarters:
        return features

    latest = snapshot.quarters[0]

    # Current margins
    features["gross_margin"] = latest.gross_margin
    features["operating_margin"] = latest.operating_margin
    features["profit_margin"] = latest.profit_margin
    features["fcf_margin"] = latest.fcf_margin

    # Margin trends (QoQ changes)
    features["gross_margin_change_qoq"] = latest.gross_margin_change_qoq
    features["operating_margin_change_qoq"] = latest.operating_margin_change_qoq

    # Margin trends (YoY changes)
    features["gross_margin_change_yoy"] = latest.gross_margin_change_yoy
    features["operating_margin_change_yoy"] = latest.operating_margin_change_yoy

    # Efficiency
    features["operating_leverage"] = latest.operating_leverage
    features["fcf_conversion"] = latest.fcf_conversion

    return features


def extract_valuation_features(snapshot: ComputedSnapshot) -> dict[str, float | None]:
    """Valuation features from multiples data."""
    features: dict[str, float | None] = {}

    if not snapshot.valuation:
        return features

    v = snapshot.valuation
    features["forward_pe"] = v.get("forward_pe")
    features["trailing_pe"] = v.get("trailing_pe")
    features["peg_ratio"] = v.get("peg_ratio")
    features["price_to_sales"] = v.get("price_to_sales")
    features["price_to_book"] = v.get("price_to_book")
    features["ev_to_revenue"] = v.get("ev_to_revenue")
    features["ev_to_ebitda"] = v.get("ev_to_ebitda")
    features["earnings_growth"] = v.get("earnings_growth")
    features["revenue_growth_fwd"] = v.get("revenue_growth")

    return features


def extract_momentum_features(snapshot: ComputedSnapshot) -> dict[str, float | None]:
    """Price momentum features."""
    return {
        "momentum_1m": snapshot.momentum_1m,
        "momentum_3m": snapshot.momentum_3m,
        "momentum_12m": snapshot.momentum_12m,
    }


async def extract_all_hard_features(
    db: AsyncSession, ticker: str
) -> dict[str, dict[str, float | None]]:
    """Extract all hard quant features for a ticker.

    Returns:
        Dict keyed by category: {
            "growth": {...},
            "profitability": {...},
            "valuation": {...},
            "momentum": {...},
        }
    """
    snapshot = await get_computed_metrics(db, ticker)

    return {
        "growth": extract_growth_features(snapshot),
        "profitability": extract_profitability_features(snapshot),
        "valuation": extract_valuation_features(snapshot),
        "momentum": extract_momentum_features(snapshot),
    }
