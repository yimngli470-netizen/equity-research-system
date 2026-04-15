"""AI-derived features — extracted from cached agent reports (JSONB).

Each agent's structured JSON output contains scores and assessments
that we map into normalized quant features.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AnalysisReport

logger = logging.getLogger(__name__)


async def _get_latest_report(
    db: AsyncSession, ticker: str, agent_type: str
) -> dict | None:
    """Fetch the most recent report for a given agent type."""
    result = await db.execute(
        select(AnalysisReport)
        .where(
            AnalysisReport.ticker == ticker,
            AnalysisReport.agent_type == agent_type,
        )
        .order_by(AnalysisReport.run_date.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row and "error" not in row.report:
        return row.report
    return None


def _extract_news_features(report: dict) -> dict[str, float | None]:
    """Extract features from news agent report."""
    features: dict[str, float | None] = {}

    # Overall sentiment: -1.0 to 1.0 → we store raw, normalize later
    features["news_sentiment"] = report.get("overall_sentiment")

    # Average impact score of news items
    items = report.get("items", [])
    if items:
        scores = [it.get("impact_score", 0) for it in items if it.get("impact_score") is not None]
        features["news_avg_impact"] = sum(scores) / len(scores) if scores else None

        # Count of positive vs negative items
        pos = sum(1 for it in items if it.get("impact_direction") == "positive")
        neg = sum(1 for it in items if it.get("impact_direction") == "negative")
        total = pos + neg
        features["news_positive_ratio"] = pos / total if total > 0 else None
    else:
        features["news_avg_impact"] = None
        features["news_positive_ratio"] = None

    return features


def _extract_earnings_features(report: dict) -> dict[str, float | None]:
    """Extract features from earnings agent report."""
    features: dict[str, float | None] = {}

    # Earnings quality score: 0-1 from the agent
    features["earnings_quality"] = report.get("earnings_quality_score")

    # Trend analysis
    trend = report.get("trend_analysis", {})
    trend_map = {"accelerating": 1.0, "expanding": 1.0, "stable": 0.5, "decelerating": 0.0, "compressing": 0.0}
    features["revenue_trend_signal"] = trend_map.get(trend.get("revenue_trend"))
    features["margin_trend_signal"] = trend_map.get(trend.get("margin_trend"))

    quality_map = {"high": 1.0, "moderate": 0.5, "low": 0.0}
    features["earnings_quality_categorical"] = quality_map.get(trend.get("earnings_quality"))

    # Forward outlook
    outlook = report.get("forward_outlook", {})
    features["fwd_revenue_signal"] = trend_map.get(outlook.get("revenue_direction"))
    features["fwd_margin_signal"] = trend_map.get(outlook.get("margin_direction"))
    confidence_map = {"high": 1.0, "moderate": 0.5, "low": 0.0}
    features["fwd_confidence"] = confidence_map.get(outlook.get("confidence"))

    # Average risk severity from risks list
    risks = report.get("risks", [])
    if risks:
        severities = [r.get("severity", 0) for r in risks if r.get("severity") is not None]
        features["earnings_risk_avg"] = sum(severities) / len(severities) if severities else None
    else:
        features["earnings_risk_avg"] = None

    return features


def _extract_industry_features(report: dict) -> dict[str, float | None]:
    """Extract features from industry agent report."""
    features: dict[str, float | None] = {}

    # Cycle position
    cycle_map = {
        "early_recovery": 0.8,
        "mid_cycle": 0.6,
        "late_cycle": 0.3,
        "downturn": 0.1,
    }
    features["cycle_position_score"] = cycle_map.get(report.get("cycle_position"))

    # Competitive position
    comp = report.get("competitive_position", {})
    share_map = {"gaining": 1.0, "stable": 0.5, "losing": 0.0}
    moat_map = {"strong": 1.0, "moderate": 0.5, "weak": 0.0}
    features["market_share_trend"] = share_map.get(comp.get("market_share_trend"))
    features["moat_strength"] = moat_map.get(comp.get("moat_strength"))

    # Average theme exposure score
    themes = report.get("theme_exposures", [])
    if themes:
        scores = [t.get("exposure_score", 0) for t in themes if t.get("exposure_score") is not None]
        features["avg_theme_exposure"] = sum(scores) / len(scores) if scores else None
    else:
        features["avg_theme_exposure"] = None

    # Average industry risk severity
    risks = report.get("industry_risks", [])
    if risks:
        severities = [r.get("severity", 0) for r in risks if r.get("severity") is not None]
        features["industry_risk_avg"] = sum(severities) / len(severities) if severities else None
    else:
        features["industry_risk_avg"] = None

    # Key indicator signals
    indicators = report.get("key_indicators", [])
    if indicators:
        signal_map = {"bullish": 1.0, "neutral": 0.5, "bearish": 0.0}
        scores = [signal_map.get(ind.get("signal"), 0.5) for ind in indicators]
        features["indicator_signal_avg"] = sum(scores) / len(scores) if scores else None
    else:
        features["indicator_signal_avg"] = None

    return features


def _extract_valuation_agent_features(report: dict) -> dict[str, float | None]:
    """Extract features from valuation agent report."""
    features: dict[str, float | None] = {}

    # Valuation score: 0-1 from agent
    features["ai_valuation_score"] = report.get("valuation_score")

    # Margin of safety
    features["margin_of_safety"] = report.get("margin_of_safety")

    # Multiples vs historical/peers
    multiples = report.get("multiples_analysis", {})
    vs_map = {"discount": 1.0, "in_line": 0.5, "premium": 0.0}
    features["vs_historical"] = vs_map.get(multiples.get("vs_historical"))
    features["vs_peers"] = vs_map.get(multiples.get("vs_peers"))

    # Verdict mapping
    verdict_map = {
        "significantly_undervalued": 1.0,
        "moderately_undervalued": 0.75,
        "fairly_valued": 0.5,
        "moderately_overvalued": 0.25,
        "significantly_overvalued": 0.0,
    }
    features["valuation_verdict_score"] = verdict_map.get(report.get("valuation_verdict"))

    # Upside/downside from target price vs current price
    target = report.get("target_price_range", {})
    current = report.get("current_price")
    if current and current > 0 and target.get("mid"):
        features["target_upside"] = (target["mid"] - current) / current
    else:
        features["target_upside"] = None

    return features


async def extract_all_ai_features(
    db: AsyncSession, ticker: str
) -> dict[str, dict[str, float | None]]:
    """Extract all AI-derived features from cached agent reports.

    Returns:
        Dict keyed by category: {
            "sentiment": {...},  (from news + industry)
            "event": {...},      (from earnings)
            "risk": {...},       (from all agents)
            "ai_valuation": {...}, (from valuation agent)
        }
    """
    news_report = await _get_latest_report(db, ticker, "news")
    earnings_report = await _get_latest_report(db, ticker, "earnings")
    industry_report = await _get_latest_report(db, ticker, "industry")
    valuation_report = await _get_latest_report(db, ticker, "valuation")

    news_feats = _extract_news_features(news_report) if news_report else {}
    earnings_feats = _extract_earnings_features(earnings_report) if earnings_report else {}
    industry_feats = _extract_industry_features(industry_report) if industry_report else {}
    valuation_feats = _extract_valuation_agent_features(valuation_report) if valuation_report else {}

    # Organize into scoring categories
    sentiment = {
        "news_sentiment": news_feats.get("news_sentiment"),
        "news_avg_impact": news_feats.get("news_avg_impact"),
        "news_positive_ratio": news_feats.get("news_positive_ratio"),
        "indicator_signal_avg": industry_feats.get("indicator_signal_avg"),
        "cycle_position_score": industry_feats.get("cycle_position_score"),
    }

    event = {
        "earnings_quality": earnings_feats.get("earnings_quality"),
        "revenue_trend_signal": earnings_feats.get("revenue_trend_signal"),
        "margin_trend_signal": earnings_feats.get("margin_trend_signal"),
        "fwd_revenue_signal": earnings_feats.get("fwd_revenue_signal"),
        "fwd_margin_signal": earnings_feats.get("fwd_margin_signal"),
        "fwd_confidence": earnings_feats.get("fwd_confidence"),
    }

    risk = {
        "earnings_risk_avg": earnings_feats.get("earnings_risk_avg"),
        "industry_risk_avg": industry_feats.get("industry_risk_avg"),
        "moat_strength": industry_feats.get("moat_strength"),
        "market_share_trend": industry_feats.get("market_share_trend"),
        "avg_theme_exposure": industry_feats.get("avg_theme_exposure"),
    }

    ai_valuation = {
        "ai_valuation_score": valuation_feats.get("ai_valuation_score"),
        "margin_of_safety": valuation_feats.get("margin_of_safety"),
        "vs_historical": valuation_feats.get("vs_historical"),
        "vs_peers": valuation_feats.get("vs_peers"),
        "valuation_verdict_score": valuation_feats.get("valuation_verdict_score"),
        "target_upside": valuation_feats.get("target_upside"),
    }

    return {
        "sentiment": sentiment,
        "event": event,
        "risk": risk,
        "ai_valuation": ai_valuation,
    }
