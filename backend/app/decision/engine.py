"""Decision engine — produces a final signal by combining scores with risk flags.

The decision engine:
1. Takes the raw composite score and signal from the scoring system
2. Runs all risk flag checks
3. Adjusts the signal based on risk flags:
   - CRITICAL flags cap the signal (no higher than HOLD)
   - MAJOR flags downgrade the signal by one level
4. Determines confidence based on data completeness and flag count
5. Generates human-readable reasoning
6. Saves the decision to stock_decisions table
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.decision.risk_flags import RiskFlag, evaluate_risk_flags
from app.models.analysis import AnalysisReport
from app.models.decision import StockDecision
from app.models.score import QuantFeature, StockScore

logger = logging.getLogger(__name__)

SIGNAL_LEVELS = ["SELL", "REDUCE", "HOLD", "BUY", "STRONG_BUY"]
CONFIDENCE_LEVELS = ["low", "moderate", "high"]


def _min_confidence(a: str, b: str | None) -> str:
    """The lower of two confidence levels (b may be None = no constraint)."""
    if b is None:
        return a
    return CONFIDENCE_LEVELS[min(
        CONFIDENCE_LEVELS.index(a) if a in CONFIDENCE_LEVELS else 1,
        CONFIDENCE_LEVELS.index(b) if b in CONFIDENCE_LEVELS else 1,
    )]


def _downgrade_signal(signal: str, steps: int = 1) -> str:
    """Downgrade a signal by N steps."""
    idx = SIGNAL_LEVELS.index(signal) if signal in SIGNAL_LEVELS else 2
    new_idx = max(0, idx - steps)
    return SIGNAL_LEVELS[new_idx]


def _cap_signal(signal: str, max_signal: str) -> str:
    """Cap a signal at a maximum level."""
    idx = SIGNAL_LEVELS.index(signal) if signal in SIGNAL_LEVELS else 2
    max_idx = SIGNAL_LEVELS.index(max_signal) if max_signal in SIGNAL_LEVELS else 2
    return SIGNAL_LEVELS[min(idx, max_idx)]


def _assess_confidence(
    feature_count: int,
    flags: list[RiskFlag],
    scores: dict[str, float],
    features: dict[str, float] | None = None,
) -> str:
    """Assess confidence in the signal based on data completeness and flags."""
    # Low confidence if few features (missing agent reports)
    if feature_count < 35:
        return "low"

    # Low confidence if many flags
    critical_count = sum(1 for f in flags if f.level == "critical")
    major_count = sum(1 for f in flags if f.level == "major")

    if critical_count >= 2:
        return "low"
    if critical_count >= 1 or major_count >= 3:
        return "moderate"

    # Validation-based confidence modifier: low reliability → downgrade
    if features:
        reliability = features.get("agent_reliability")
        if reliability is not None and reliability < 0.5:
            return "low"
        contradiction_rate = features.get("contradiction_rate")
        if contradiction_rate is not None and contradiction_rate > 0.3:
            return "moderate"

    # Check for extreme scores (very high conviction either way)
    composite_values = list(scores.values())
    if all(v > 0.7 for v in composite_values) or all(v < 0.3 for v in composite_values):
        return "high"

    # Decent data coverage, not too many flags
    if feature_count >= 45 and major_count <= 1:
        return "high"

    return "moderate"


def _build_reasoning(
    raw_signal: str,
    final_signal: str,
    scores: dict[str, float],
    flags: list[RiskFlag],
    confidence: str,
) -> str:
    """Generate human-readable reasoning for the decision."""
    parts = []

    # Lead with the final signal
    if final_signal == raw_signal:
        parts.append(f"Signal: {final_signal} (no adjustment).")
    else:
        parts.append(f"Signal adjusted from {raw_signal} (quant screen) to {final_signal}.")

    # Highlight strongest and weakest categories
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top = sorted_scores[0]
    bottom = sorted_scores[-1]
    parts.append(f"Strongest: {top[0]} ({top[1]:.2f}). Weakest: {bottom[0]} ({bottom[1]:.2f}).")

    # Summarize flags
    critical_count = sum(1 for f in flags if f.level == "critical")
    major_count = sum(1 for f in flags if f.level == "major")
    watch_count = sum(1 for f in flags if f.level == "watch")

    if flags:
        flag_parts = []
        if critical_count:
            flag_parts.append(f"{critical_count} critical")
        if major_count:
            flag_parts.append(f"{major_count} major")
        if watch_count:
            flag_parts.append(f"{watch_count} watch")
        parts.append(f"Risk flags: {', '.join(flag_parts)}.")
    else:
        parts.append("No risk flags triggered.")

    parts.append(f"Confidence: {confidence}.")

    return " ".join(parts)


def _apply_judge_gate(signal: str, judge: dict) -> tuple[str, str | None, list[str]]:
    """The dialectic judge (2.1) binds the decision: a bearish or low-conviction verdict caps the
    signal (and confidence), so a high quant screen can't ship as a strong buy the analyst doubts.
    Only ever *lowers* the signal — never raises it. Returns (signal, confidence_ceiling, notes)."""
    notes: list[str] = []
    leaning = str(judge.get("leaning") or "").lower()
    conviction = judge.get("conviction")

    leaning_cap = {"strong_bear": "REDUCE", "bear": "HOLD", "neutral": "HOLD"}.get(leaning)
    if leaning_cap:
        capped = _cap_signal(signal, leaning_cap)
        if capped != signal:
            notes.append(f"judge leaning '{leaning}' caps signal to {leaning_cap}")
        signal = capped

    ceiling: str | None = None
    if isinstance(conviction, (int, float)):
        if conviction < 0.35:
            capped = _cap_signal(signal, "HOLD")
            if capped != signal:
                notes.append(f"judge conviction {conviction:.2f} (<0.35) caps signal to HOLD")
            signal, ceiling = capped, "low"
        elif conviction < 0.5:
            capped = _cap_signal(signal, "BUY")
            if capped != signal:
                notes.append(f"judge conviction {conviction:.2f} (<0.5) caps STRONG_BUY to BUY")
            signal, ceiling = capped, "moderate"
        elif conviction < 0.6:
            ceiling = "moderate"
    return signal, ceiling, notes


def _apply_validation_gate(signal: str, validation: dict | None) -> tuple[str, str | None, list[str]]:
    """Evidence gate (2.4): if the validation agent found the report's claims largely unverifiable
    or contradicted, a buy cannot ship — cap at HOLD and force low confidence.

    Reads RAW values straight from the validation report (reliability_score, contradicted/total) —
    not the normalized quant feature, where `contradiction_rate` is inverted (high = good)."""
    if not validation:
        return signal, None, []
    summary = validation.get("summary") or {}
    reliability = summary.get("reliability_score")
    total = summary.get("total_checks") or 0
    contradicted = summary.get("contradicted") or 0
    contra_rate = (contradicted / total) if total else 0.0

    if (isinstance(reliability, (int, float)) and reliability < 0.4) or contra_rate > 0.4:
        capped = _cap_signal(signal, "HOLD")
        note = [f"evidence gate: reliability={reliability}, {contradicted}/{total} claims contradicted → caps to HOLD"]
        return capped, "low", note
    return signal, None, []


@dataclass
class DecisionResult:
    ticker: str
    date: date
    raw_signal: str
    raw_composite: float
    final_signal: str
    confidence: str
    risk_flags: list[dict]
    reasoning: str
    scores: dict[str, float]
    judge_leaning: str | None = None
    judge_conviction: float | None = None


async def run_decision(
    db: AsyncSession,
    ticker: str,
) -> DecisionResult:
    """Run the decision engine for a ticker.

    Requires scoring to have been run first (reads from stock_scores + quant_features).
    """
    today = date.today()

    # Fetch latest score
    score_result = await db.execute(
        select(StockScore)
        .where(StockScore.ticker == ticker)
        .order_by(StockScore.date.desc())
        .limit(1)
    )
    score = score_result.scalar_one_or_none()

    if not score:
        raise ValueError(f"No score found for {ticker}. Run scoring first.")

    scores = {
        "growth": score.growth_score,
        "profitability": score.profitability_score,
        "valuation": score.valuation_score,
        "momentum": score.momentum_score,
        "sentiment": score.sentiment_score,
        "risk": score.risk_score,
        "event": score.event_score,
    }
    raw_signal = score.signal
    raw_composite = score.composite_score

    # Fetch latest features as a flat dict
    feat_result = await db.execute(
        select(QuantFeature)
        .where(QuantFeature.ticker == ticker)
        .order_by(QuantFeature.date.desc())
        .limit(100)
    )
    all_features = feat_result.scalars().all()

    # Only use the latest date
    features: dict[str, float] = {}
    feature_count = 0
    if all_features:
        latest_date = all_features[0].date
        for f in all_features:
            if f.date == latest_date:
                features[f.feature_name] = f.feature_value
                feature_count += 1

    # Run risk flags
    flags = evaluate_risk_flags(scores, features)

    # Adjust signal based on flags
    final_signal = raw_signal

    critical_flags = [f for f in flags if f.level == "critical"]
    major_flags = [f for f in flags if f.level == "major"]

    # Critical flags: cap at HOLD (never recommend buying with critical risks)
    if critical_flags:
        final_signal = _cap_signal(final_signal, "HOLD")

    # Major flags: each one downgrades by one step (max 2 downgrades from major)
    major_downgrades = min(len(major_flags), 2)
    if major_downgrades > 0:
        final_signal = _downgrade_signal(final_signal, major_downgrades)

    # Assess confidence from data completeness + flags + validation reliability
    confidence = _assess_confidence(feature_count, flags, scores, features)

    # Wire the dialectic judge (2.1) + the evidence gate into the decision (roadmap 2.4). These can
    # only LOWER the signal/confidence — the reasoning layer's skepticism binds the quant screen.
    judge = (
        await db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.ticker == ticker, AnalysisReport.agent_type == "judge")
            .order_by(AnalysisReport.run_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    judge_report = judge.report if judge and isinstance(judge.report, dict) and "error" not in judge.report else None

    judge_leaning = judge_conviction = None
    adjustments: list[str] = []
    if judge_report:
        judge_leaning = judge_report.get("leaning")
        jc = judge_report.get("conviction")
        judge_conviction = float(jc) if isinstance(jc, (int, float)) else None
        final_signal, ceiling, notes = _apply_judge_gate(final_signal, judge_report)
        confidence = _min_confidence(confidence, ceiling)
        adjustments += notes

    validation = (
        await db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.ticker == ticker, AnalysisReport.agent_type == "validation")
            .order_by(AnalysisReport.run_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    validation_report = validation.report if validation and isinstance(validation.report, dict) and "error" not in validation.report else None
    final_signal, val_ceiling, val_notes = _apply_validation_gate(final_signal, validation_report)
    confidence = _min_confidence(confidence, val_ceiling)
    adjustments += val_notes

    # Build reasoning
    reasoning = _build_reasoning(raw_signal, final_signal, scores, flags, confidence)
    if judge_report:
        conv_txt = f"{judge_conviction:.2f}" if judge_conviction is not None else "n/a"
        reasoning += f" Judge leaning: {judge_leaning or 'n/a'} (conviction {conv_txt})."
    if adjustments:
        reasoning += " Adjustments: " + "; ".join(adjustments) + "."
    reasoning = reasoning[:1000]

    # Save to DB
    flag_dicts = [f.to_dict() for f in flags]

    existing = await db.execute(
        select(StockDecision).where(
            StockDecision.ticker == ticker,
            StockDecision.date == today,
        )
    )
    row = existing.scalar_one_or_none()

    if row:
        row.raw_signal = raw_signal
        row.raw_composite = raw_composite
        row.final_signal = final_signal
        row.confidence = confidence
        row.risk_flags = flag_dicts
        row.reasoning = reasoning
        row.judge_leaning = judge_leaning
        row.judge_conviction = judge_conviction
    else:
        db.add(StockDecision(
            ticker=ticker,
            date=today,
            raw_signal=raw_signal,
            raw_composite=raw_composite,
            final_signal=final_signal,
            confidence=confidence,
            risk_flags=flag_dicts,
            reasoning=reasoning,
            judge_leaning=judge_leaning,
            judge_conviction=judge_conviction,
        ))

    await db.commit()

    # Thesis journal (roadmap 3.1): snapshot this verdict as the last pipeline step (run-once, not a
    # scheduler). Best-effort — journaling must never break the decision.
    try:
        from app.thesis.journal import snapshot_thesis
        await snapshot_thesis(db, ticker, decision_signal=final_signal)
    except Exception:
        logger.exception("[thesis] snapshot failed for %s", ticker)

    logger.info(
        "[decision] %s → raw=%s final=%s confidence=%s flags=%d",
        ticker, raw_signal, final_signal, confidence, len(flags),
    )

    return DecisionResult(
        ticker=ticker,
        date=today,
        raw_signal=raw_signal,
        raw_composite=raw_composite,
        final_signal=final_signal,
        confidence=confidence,
        risk_flags=flag_dicts,
        reasoning=reasoning,
        scores=scores,
        judge_leaning=judge_leaning,
        judge_conviction=judge_conviction,
    )
