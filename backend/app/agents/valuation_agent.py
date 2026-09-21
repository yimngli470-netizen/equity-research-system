"""Valuation Analyst Agent — multiples analysis, DCF assessment, target price range."""

import logging
import json
import hashlib
from app.valuation_model.economics import MODEL_VERSION
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.transcript_summarizer import format_summary_for_agent
from app.ingestion.computed_metrics import format_for_llm, get_computed_metrics
from app.measurement.normalized_earnings import compute_normalized_earnings
from app.models.estimate import AnalystEstimate
from app.models.stock import Stock
from app.models.transcript import EarningsTranscript
from app.models.valuation import Valuation

logger = logging.getLogger(__name__)


def _format_normalized_earnings(archetype: str | None, ne, market_cap: float | None) -> str:
    """Render the mid-cycle / normalized-earnings block (roadmap 2.2), branched on whether the name
    is actually a cyclical (only then is median-reversion the right model)."""
    if ne is None:
        return ""
    lines = ["=== REGIME / NORMALIZED EARNINGS (measured from filed history) ==="]
    if archetype:
        lines.append(f"Business-model archetype: {archetype}")

    # The current vs mid-cycle margin is informative context for any name.
    if ne.current_net_margin is not None and ne.midcycle_net_margin is not None:
        lines.append(
            f"Net margin — current TTM {ne.current_net_margin:.1%} vs 5yr median "
            f"{ne.midcycle_net_margin:.1%} (range {ne.trough_net_margin:.1%}..{ne.peak_net_margin:.1%})"
            + (f"  → current is {ne.margin_ratio}x median" if ne.margin_ratio else "")
        )

    if ne.basis == "cyclical":
        lines.append(f"Cycle position: {ne.cycle_position} (this IS a margin-cyclical business)")
        if ne.ttm_net_income is not None and ne.normalized_net_income is not None:
            lines.append(
                f"Net income — current TTM ${ne.ttm_net_income/1e9:.2f}B vs NORMALIZED (mid-cycle margin) "
                f"${ne.normalized_net_income/1e9:.2f}B  (normalized is {ne.normalized_factor}x of spot)"
            )
            if market_cap and ne.ttm_net_income and ne.normalized_net_income and ne.normalized_net_income > 0:
                lines.append(
                    f"Implied P/E — SPOT ≈ {market_cap/ne.ttm_net_income:.1f}x  vs  "
                    f"NORMALIZED ≈ {market_cap/ne.normalized_net_income:.1f}x"
                )
        lines.append(
            "NOTE: this is a cyclical — a low SPOT multiple on PEAK earnings is a trap. Anchor your "
            "fair value on the NORMALIZED (mid-cycle) earnings, not spot."
        )
    elif ne.basis == "inflection":
        lines.append(
            "Margin regime: INFLECTION — the historical median margin is non-positive (a losses→profits "
            "transition), so a historical-median normalization is INVALID. Value on CURRENT/FORWARD "
            "earnings, not a backward cycle average."
        )
    else:  # stable
        lines.append(
            "Margin regime: STABLE — not a commodity cyclical, so spot earnings are the right basis "
            "(no cycle-normalization). If current margins sit well ABOVE the 5yr median, weigh how "
            "durable that expansion is (secular vs temporary) rather than mechanically mean-reverting."
        )
    return "\n".join(lines)


class ValuationAgent(BaseAgent):
    agent_type = "valuation"
    max_age_days = 7  # refresh weekly
    tier = "opus"
    # Price compared with a ±5% relative band: daily wiggles don't change a valuation thesis;
    # a real move does (and multiples scale with price, so the band covers them too).
    fingerprint_tolerances = {"price": ("rel", 0.05)}

    async def compute_fingerprint(self, db: AsyncSession, ticker: str) -> dict:
        from app.agents import fingerprints as fp
        from app.forecast.engine import _latest_forecast
        f = await _latest_forecast(db, ticker)
        from app.models.forecast import Forecast
        stock = await db.get(Stock, ticker)
        peers = (await db.execute(select(Forecast.ticker, Forecast.as_of, Forecast.projections)
            .join(Stock, Stock.ticker == Forecast.ticker)
            .where(Stock.industry == stock.industry if stock else False)
            .distinct(Forecast.ticker).order_by(Forecast.ticker, Forecast.as_of.desc()))).all()
        peer_marker = hashlib.sha256(json.dumps([(p.ticker, str(p.as_of), p.projections) for p in peers], sort_keys=True).encode()).hexdigest()[:16]
        return {
            "valuation_model": MODEL_VERSION,
            "peer_forecasts": peer_marker,
            "financials": await fp.financial_marker(db, ticker),
            "transcript": await fp.transcript_marker(db, ticker),
            "estimates": await fp.estimates_marker(db, ticker),
            "targets": await fp.price_targets_marker(db, ticker),
            "price": await fp.price_marker(db, ticker),
            # A new forecast (4.2) re-anchors forward earnings power → re-run the valuation.
            "forecast": f"{f.id}.{f.as_of}" if f is not None else None,
        }

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        snapshot = await get_computed_metrics(db, ticker)
        context = format_for_llm(snapshot)

        # Regime-aware valuation (roadmap 2.2): give the agent the archetype + the through-cycle
        # normalized-earnings view so it values cyclicals on mid-cycle, not peak, earnings.
        stock = await db.get(Stock, ticker)
        archetype = stock.archetype if stock else None
        ne = await compute_normalized_earnings(db, ticker, archetype)
        market_cap = (snapshot.valuation or {}).get("market_cap") if snapshot.valuation else None
        regime_block = _format_normalized_earnings(archetype, ne, market_cap)
        if regime_block:
            context += "\n\n" + regime_block

        # Add analyst consensus estimates (next 4 quarters)
        result = await db.execute(
            select(AnalystEstimate)
            .where(AnalystEstimate.ticker == ticker, AnalystEstimate.period_type != "legacy")
            .where(AnalystEstimate.period_end_date >= date.today())
            .order_by(AnalystEstimate.period_end_date.asc())
            .limit(4)
        )
        estimates = result.scalars().all()
        if estimates:
            # Forward EPS/revenue consensus is a meaningful reference (normal weight). It is
            # only discounted when genuinely stale: our copy >3 months old, or no analyst
            # revisions in the last ~3 months.
            ages = [(date.today() - e.as_of).days for e in estimates if e.as_of]
            copy_age = min(ages) if ages else None
            revs = [e.revisions_30d for e in estimates if e.revisions_30d is not None]
            no_recent_revisions = bool(revs) and max(revs) == 0
            stale = (copy_age is not None and copy_age > 90) or no_recent_revisions

            lines = ["--- ANALYST CONSENSUS ESTIMATES (forward EPS/revenue — a meaningful reference) ---"]
            if stale:
                why = []
                if copy_age is not None and copy_age > 90:
                    why.append(f"our copy is {copy_age} days old (>3 months)")
                if no_recent_revisions:
                    why.append("no analyst revisions in the last 30 days")
                lines.append(f"  ⚠ STALE ({'; '.join(why)}) — discount heavily; treat as absent.")
            for e in estimates:
                parts = [f"  {e.period_type} ending {e.period_end_date} ({e.date_precision}; EPS basis {e.accounting_basis}):"]
                if e.eps_consensus is not None:
                    parts.append(f"EPS consensus=${e.eps_consensus:.2f} (low={e.eps_low}, high={e.eps_high})")
                if e.revenue_consensus is not None:
                    parts.append(f"Rev consensus=${e.revenue_consensus / 1e9:.2f}B")
                if e.number_of_analysts:
                    parts.append(f"({e.number_of_analysts} analysts)")
                if e.revisions_30d is not None:
                    parts.append(f"[revisions last 30d: {e.revisions_30d}]")
                lines.append(" ".join(parts))
            context += "\n\n" + "\n".join(lines)

        # Analyst PRICE TARGET — LOW weight (frequently way off); a loose divergence anchor only.
        val = (await db.execute(
            select(Valuation).where(Valuation.ticker == ticker)
            .order_by(Valuation.date.desc()).limit(1)
        )).scalar_one_or_none()
        if val and val.target_mean_price:
            age = (date.today() - val.date).days if val.date else None
            stale_pt = " ⚠ STALE (>3 months old)" if age is not None and age > 90 else ""
            n = f", {val.num_price_target_analysts} analysts" if val.num_price_target_analysts else ""
            context += (
                "\n\n--- ANALYST PRICE TARGET (LOW-WEIGHT — these are frequently far off; "
                "use only as a loose divergence check, never as your target)" + stale_pt + " ---\n"
                f"  mean=${val.target_mean_price:.0f} median=${val.target_median_price or 0:.0f} "
                f"low=${val.target_low_price or 0:.0f} high=${val.target_high_price or 0:.0f}{n}"
            )

        # Add guidance excerpts from most recent transcript
        result = await db.execute(
            select(EarningsTranscript)
            .where(EarningsTranscript.ticker == ticker)
            .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
            .limit(1)
        )
        transcript = result.scalar_one_or_none()
        if transcript and transcript.summary:
            block = format_summary_for_agent(transcript.summary, focus="valuation")
            if block:
                context += f"\n\n{block}"
        elif transcript:
            logger.warning(
                "[valuation] %s Q%d %d transcript has no summary — skipping transcript context",
                ticker, transcript.quarter, transcript.year,
            )

        # OUR MODEL (roadmap 4.2): the driver-based forecast — our own numbers, the primary
        # anchor for forward earnings power. Triangulate: our model vs street vs your DCF.
        from app.forecast.engine import _latest_forecast, summarize_forecast
        f = await _latest_forecast(db, ticker)
        if f is not None:
            context += "\n\n--- OUR FORECAST MODEL (4.2; basis-cited, deterministic compile) ---\n"
            context += summarize_forecast(f)

        from app.valuation_model.target import compute_price_target
        from app.valuation_model.presentation import price_target_payload
        model = price_target_payload(await compute_price_target(db, ticker, None, persist=False))
        if not hasattr(self, "_model_values"):
            self._model_values = {}
        self._model_values[ticker] = model
        context += "\n\n=== DETERMINISTIC VALUATION — THE ONLY SOURCE OF NUMERIC VALUE CLAIMS ===\n" + json.dumps(model)
        return context

    def get_system_prompt(self) -> str:
        return """You are a senior valuation analyst explaining a deterministic scenario model.
Use ONLY the supplied evidence. The DETERMINISTIC VALUATION block owns all numeric DCF values,
price targets, discount rates and probabilities. Do not run your own mental DCF or invent a
replacement target. Numeric output fields are populated by code after your response.

Explain whether this company's growth duration, operating margin path, reinvestment/cash conversion,
dilution and risk justify the chosen method. Companies sharing an archetype can have different
economics. Small market cap by itself earns no premium. Cyclicals use normalized earning power;
financial companies need capital/distribution models. Identify unsupported assumptions honestly.
Compare like periods and accounting bases: fiscal-year estimates are not NTM; provider-unspecified
EPS is not GAAP. Explain material disagreement with street targets as a difference in assumptions,
not proof either number is correct. A large downside gap calls for thesis/assumption review,
not an instruction to wait indefinitely for a lower share price. Our base scenario and the judge's
probability-weighted headline differ by construction; present DCF and future targets have different dates.
If the model status is unavailable, say why and leave value judgments unknown. Never fill the gap
with an invented value. Critique model limitations including the historical cash-conversion proxy,
zero net borrowing, share funding and declared policy priors. Do not describe those priors as calibrated.

Keep the explanation compact: summary at most 90 words, model_assessment at most 180 words,
and each other prose field at most 60 words. The interface already displays all numeric model
outputs. Do not repeat dollar prices, EPS amounts, percentages, or multiples in prose, and do not
perform new arithmetic or numeric comparisons in prose. Explain the business assumptions and
the meaning of differences instead. Compare growth only over matching periods: a reported
year-over-year quarter and a modeled future year are not interchangeable. Peer distance weights
are relative closeness scores used in a weighted median; they do not need to sum to one.
When cash flow constrains buybacks, the calculator carries additional dilution into the funded
EPS and DCF path. The requested forecast remains in the audit; no revenue or profit is raised
to fund repurchases. Explain any adjustment as a capital-allocation assumption.
The headline present DCF weights scenarios, while intrinsic_value_base is the base present DCF;
the DCF leg in a scenario target is a FUTURE-date value. Never interchange these quantities.

Respond with JSON only, using these qualitative fields (no numeric target fields):
{
 "ticker": "string",
 "regime": {"cycle_position": "peak | mid | trough | not_cyclical", "earnings_basis": "string", "re_rate_vs_peak": "string"},
 "multiples_analysis": {"pe_assessment": "string", "ps_assessment": "string", "ev_ebitda_assessment": "string", "vs_historical": "premium | in_line | discount | unknown", "vs_peers": "premium | in_line | discount | unknown"},
 "model_assessment": "string — critique suitability, growth duration, margin durability, reinvestment and financing assumptions",
 "consensus_comparison": {"your_eps_vs_consensus": "above | in_line | below | unknown", "your_revenue_vs_consensus": "above | in_line | below | unknown", "divergence_reasoning": "string"},
 "guidance_assessment": {"management_guidance_tone": "confident | cautious | vague | unknown", "guidance_vs_consensus": "above | in_line | below | unknown", "key_guidance_points": ["string"]},
 "triangulation": {"divergence_justification": "string", "vs_management_guidance": "above | in_line | below | unknown", "reconciliation": "string"},
 "summary": "string — concise valuation conclusion and which assumptions would change it"
}
Use null for consensus_comparison or guidance_assessment when evidence is unavailable."""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return f"Explain and challenge the supplied deterministic valuation for {ticker}.\n\n{context}\n\nRespond with JSON only."

    def postprocess_report(self, report: dict, ticker: str) -> dict:
        report = super().postprocess_report(report, ticker)
        model = getattr(self, "_model_values", {}).pop(ticker, None) or {}
        ready = (model.get("method") or {}).get("status") == "ready"
        scenarios = model.get("scenarios") or {}
        base = scenarios.get("base") or {}
        fair = base.get("dcf_today") if ready else None
        target = base.get("blended") if ready else None
        price = model.get("price_at")
        upside = fair / price - 1 if fair is not None and price and ready else None
        report["valuation_model"] = {"version": MODEL_VERSION, "status": "verified" if ready else "unavailable",
            "as_of": model.get("as_of"), "forecast_as_of": model.get("forecast_as_of"),
            "target_date": (model.get("method") or {}).get("target_date"),
            "issues": (model.get("method") or {}).get("issues") or [],
            "method": model.get("method"), "source": "same deterministic calculator as the decision price target"}
        report["current_price"] = price
        report["dcf_analysis"] = {
            "intrinsic_value_base": fair,
            "intrinsic_value_bear": (scenarios.get("bear") or {}).get("dcf_today") if ready else None,
            "intrinsic_value_bull": (scenarios.get("bull") or {}).get("dcf_today") if ready else None,
            "assumptions": {"cost_of_equity": (model.get("wacc") or {}).get("cost_of_equity"),
                            "terminal_growth": (model.get("method") or {}).get("terminal_growth")},
            "methodology_note": "Present equity DCF, calculated in code. The future target uses the same forecast; the decision headline weights all three scenarios."}
        vals = [s.get("blended") for s in scenarios.values() if s.get("blended") is not None] if ready else []
        report["target_price_range"] = {"low": min(vals) if vals else None, "mid": target, "high": max(vals) if vals else None}
        report["margin_of_safety"] = upside
        verdict = "unknown" if upside is None else (
            "significantly_undervalued" if upside >= .30 else "moderately_undervalued" if upside >= .10 else
            "significantly_overvalued" if upside <= -.30 else "moderately_overvalued" if upside <= -.10 else "fairly_valued")
        report["valuation_verdict"] = verdict
        report["valuation_score"] = {"significantly_undervalued": 1., "moderately_undervalued": .75,
            "fairly_valued": .5, "moderately_overvalued": .25, "significantly_overvalued": 0.}.get(verdict)
        tri = report.get("triangulation") if isinstance(report.get("triangulation"), dict) else {}
        street = model.get("street_target_mean")
        div = target / street - 1 if target is not None and street and ready else None
        tri.update(your_fair_value=fair, your_target_price=target, street_mean_target=street,
                   divergence_pct=round(div, 4) if div is not None else None,
                   comparison_basis="base future target vs street target; present DCF shown separately")
        if div is not None and abs(div) > .20 and not tri.get("divergence_justification"):
            tri["divergence_justification"] = "Large divergence remains unexplained; review assumptions before using this target."
        report["triangulation"] = tri
        return report
