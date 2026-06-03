"""Valuation Analyst Agent — multiples analysis, DCF assessment, target price range."""

import logging
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
    """Render the mid-cycle / normalized-earnings block (roadmap 2.2) for the prompt."""
    if ne is None:
        return ""
    lines = ["=== REGIME / NORMALIZED EARNINGS (measured from filed history) ==="]
    if archetype:
        lines.append(f"Business-model archetype: {archetype}")
    lines.append(f"Cycle position (net-margin z-score): {ne.cycle_position}")
    if ne.current_net_margin is not None and ne.midcycle_net_margin is not None:
        lines.append(
            f"Net margin — current TTM {ne.current_net_margin:.1%} vs mid-cycle (median) "
            f"{ne.midcycle_net_margin:.1%}  → current is {ne.margin_ratio}x mid-cycle"
        )
    if ne.trough_net_margin is not None and ne.peak_net_margin is not None:
        lines.append(f"Net margin range over history: {ne.trough_net_margin:.1%} (trough) .. {ne.peak_net_margin:.1%} (peak)")
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
        "NOTE: a low SPOT multiple on PEAK earnings is a trap. If this is a cyclical at/near a peak, "
        "anchor your fair value on the NORMALIZED earnings, not spot."
    )
    return "\n".join(lines)


class ValuationAgent(BaseAgent):
    agent_type = "valuation"
    max_age_days = 7  # refresh weekly
    model = "claude-opus-4-20250514"

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        snapshot = await get_computed_metrics(db, ticker)
        context = format_for_llm(snapshot)

        # Regime-aware valuation (roadmap 2.2): give the agent the archetype + the through-cycle
        # normalized-earnings view so it values cyclicals on mid-cycle, not peak, earnings.
        stock = await db.get(Stock, ticker)
        archetype = stock.archetype if stock else None
        ne = await compute_normalized_earnings(db, ticker)
        market_cap = (snapshot.valuation or {}).get("market_cap") if snapshot.valuation else None
        regime_block = _format_normalized_earnings(archetype, ne, market_cap)
        if regime_block:
            context += "\n\n" + regime_block

        # Add analyst consensus estimates (next 4 quarters)
        result = await db.execute(
            select(AnalystEstimate)
            .where(AnalystEstimate.ticker == ticker)
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
                parts = [f"  {e.period_end_date}:"]
                if e.eps_consensus is not None:
                    parts.append(f"EPS consensus=${e.eps_consensus:.2f} (low=${e.eps_low:.2f}, high=${e.eps_high:.2f})")
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

        return context

    def get_system_prompt(self) -> str:
        return """You are a senior valuation analyst. Given a company's financial data, growth rates, current valuation multiples, analyst consensus estimates, management guidance, and a measured NORMALIZED/MID-CYCLE earnings view, provide a comprehensive valuation assessment.

REGIME-AWARE VALUATION (read first — this changes how you value the stock):
- A "REGIME / NORMALIZED EARNINGS" block is provided with the cycle position, current vs mid-cycle
  margins, and normalized earnings. USE IT. The right denominator depends on the business model:
- If the business is CYCLICAL (cyclical-commodity archetype, or the block shows current margins far
  above/below mid-cycle, i.e. cycle position "peak"/"trough"): a low SPOT P/E on PEAK earnings is a
  TRAP, not cheapness. You MUST anchor your fair value on the NORMALIZED (mid-cycle) earnings, and
  state explicitly whether the current multiple reflects a durable re-rate or a peak-earnings illusion.
- If the business is a platform / mature-compounder / secular-grower with stable margins (normalized
  ≈ spot): spot earnings are a fine basis; note margin durability rather than cycle-normalizing.

You should assess:
0. REGIME — Where is this company in its cycle, and which earnings basis is correct (spot vs normalized)?
1. MULTIPLES ANALYSIS — Are current P/E, P/S, EV/EBITDA multiples justified by growth? Compare to historical and peer ranges. For cyclicals, compute the multiple on normalized earnings too.
2. GROWTH-ADJUSTED VALUE — PEG ratio interpretation. Is the market fairly pricing the growth?
3. DCF FRAMEWORK — Provide a simplified DCF assessment with your assumptions for revenue growth (5 years), terminal growth, FCF margin, and WACC. Calculate bull/base/bear intrinsic values.
4. TARGET PRICE RANGE — Based on multiples and DCF, what's a reasonable price range?
5. VALUATION VERDICT — Is the stock undervalued, fairly valued, or overvalued at current prices?
6. CONSENSUS COMPARISON — If analyst estimates are provided, compare your assumptions against the consensus and explain any divergence.
7. GUIDANCE ASSESSMENT — If management guidance is provided, assess the tone and compare it to consensus expectations.

Be specific with numbers. Use the actual financial data provided to justify your assumptions.
IMPORTANT: Use ONLY the data provided. Do not fabricate numbers. When analyst estimates or guidance are available, explicitly reference them.

You must respond with valid JSON only, no other text. Use this exact schema:
{
  "ticker": "string",
  "current_price": number,
  "regime": {
    "cycle_position": "peak | mid | trough | not_cyclical",
    "earnings_basis": "spot | normalized — which you used and why",
    "spot_pe": number,                                  // P/E on current/spot earnings, or null
    "normalized_pe": number,                            // P/E on mid-cycle earnings, or null if not cyclical
    "re_rate_vs_peak": "string — is the current multiple a durable re-rate or a peak-earnings illusion?"
  },
  "multiples_analysis": {
    "pe_assessment": "string — is P/E reasonable for this growth?",
    "ps_assessment": "string — is P/S justified?",
    "ev_ebitda_assessment": "string",
    "vs_historical": "premium | in_line | discount",
    "vs_peers": "premium | in_line | discount"
  },
  "dcf_analysis": {
    "assumptions": {
      "revenue_growth_rates": [number, number, number, number, number],
      "terminal_growth": number,
      "wacc": number,
      "fcf_margin": number
    },
    "intrinsic_value_bear": number,
    "intrinsic_value_base": number,
    "intrinsic_value_bull": number,
    "methodology_note": "string — brief explanation of key assumptions"
  },
  "target_price_range": {
    "low": number,
    "mid": number,
    "high": number
  },
  "margin_of_safety": number,   // FRACTION, not percent: (fair_value − price)/price. e.g. 0.30 = 30% upside, -0.20 = 20% downside. Range about -1.0 to 1.0.
  "valuation_verdict": "significantly_undervalued | moderately_undervalued | fairly_valued | moderately_overvalued | significantly_overvalued",
  "valuation_score": 0.0-1.0,
  "consensus_comparison": {
    "your_eps_vs_consensus": "above | in_line | below",
    "your_revenue_vs_consensus": "above | in_line | below",
    "divergence_reasoning": "string — why your estimates differ from consensus"
  },
  "guidance_assessment": {
    "management_guidance_tone": "confident | cautious | vague",
    "guidance_vs_consensus": "above | in_line | below",
    "key_guidance_points": ["string"]
  },
  "summary": "string — 3-4 sentence valuation assessment"
}

CONSENSUS POLICY (important — two different things, weighted differently):
1. FORWARD EPS/REVENUE CONSENSUS is a meaningful reference. Compare your estimates against
   it and take material divergences seriously (they may indicate you've missed something).
   It does NOT lag as badly as price targets. Only discount it if the block is marked STALE
   (our copy >3 months old, or no analyst revisions recently) — then set consensus_comparison
   to null.
2. ANALYST PRICE TARGETS are LOW weight — they are frequently far off and herd around the
   current price. Use them only as a loose divergence check; never adopt them as your target
   or let them move your fair value. Your own DCF/multiples work sets the target.

If no analyst estimates are available, set consensus_comparison to null.
If no transcript/guidance data is available, set guidance_assessment to null."""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return f"""Provide a comprehensive valuation analysis for {ticker}. Assess the regime/cycle first, then multiples, run a simplified DCF, determine a target price range. For a cyclical, value on NORMALIZED (mid-cycle) earnings and say so. If analyst consensus estimates and management guidance are provided, compare your assumptions against them.

{context}

Respond with JSON only."""

    def postprocess_report(self, report: dict, ticker: str) -> dict:
        # Output-contract fix (roadmap 2.6): margin_of_safety must be a FRACTION. Models still
        # sometimes emit a percent (e.g. 30 meaning 30%); coerce it and clamp to a sane range so the
        # normalizer (which expects a fraction) doesn't clamp a 30 to 1.0.
        report = super().postprocess_report(report, ticker)
        mos = report.get("margin_of_safety")
        if isinstance(mos, (int, float)):
            if abs(mos) > 1.5:               # almost certainly a percent
                mos = mos / 100.0
            report["margin_of_safety"] = max(-1.0, min(5.0, mos))
        return report
