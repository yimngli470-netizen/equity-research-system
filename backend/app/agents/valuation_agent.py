"""Valuation Analyst Agent — multiples analysis, DCF assessment, target price range."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.transcript_utils import extract_guidance_mentions
from app.ingestion.computed_metrics import format_for_llm, get_computed_metrics
from app.models.estimate import AnalystEstimate
from app.models.transcript import EarningsTranscript


class ValuationAgent(BaseAgent):
    agent_type = "valuation"
    max_age_days = 7  # refresh weekly
    model = "claude-opus-4-20250514"

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        snapshot = await get_computed_metrics(db, ticker)
        context = format_for_llm(snapshot)

        # Add analyst consensus estimates (next 4 quarters)
        result = await db.execute(
            select(AnalystEstimate)
            .where(AnalystEstimate.ticker == ticker)
            .order_by(AnalystEstimate.period_end_date.asc())
            .limit(4)
        )
        estimates = result.scalars().all()
        if estimates:
            lines = ["--- ANALYST CONSENSUS ESTIMATES ---"]
            for e in estimates:
                parts = [f"  {e.period_end_date}:"]
                if e.eps_consensus is not None:
                    parts.append(f"EPS consensus=${e.eps_consensus:.2f} (low=${e.eps_low:.2f}, high=${e.eps_high:.2f})")
                if e.revenue_consensus is not None:
                    rev_b = e.revenue_consensus / 1e9
                    parts.append(f"Rev consensus=${rev_b:.2f}B")
                if e.number_of_analysts:
                    parts.append(f"({e.number_of_analysts} analysts)")
                lines.append(" ".join(parts))
            context += "\n\n" + "\n".join(lines)

        # Add guidance excerpts from most recent transcript
        result = await db.execute(
            select(EarningsTranscript)
            .where(EarningsTranscript.ticker == ticker)
            .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
            .limit(1)
        )
        transcript = result.scalar_one_or_none()
        if transcript:
            guidance = extract_guidance_mentions(transcript.full_text)
            if guidance:
                context += f"\n\n{guidance}"

        return context

    def get_system_prompt(self) -> str:
        return """You are a senior valuation analyst. Given a company's financial data, growth rates, current valuation multiples, analyst consensus estimates, and management guidance from earnings calls, provide a comprehensive valuation assessment.

You should assess:
1. MULTIPLES ANALYSIS — Are current P/E, P/S, EV/EBITDA multiples justified by growth? Compare to historical and peer ranges.
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
  "margin_of_safety": number,
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

If no analyst estimates are available, set consensus_comparison to null.
If no transcript/guidance data is available, set guidance_assessment to null."""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return f"""Provide a comprehensive valuation analysis for {ticker}. Assess multiples, run a simplified DCF, determine a target price range. If analyst consensus estimates and management guidance are provided, compare your assumptions against them.

{context}

Respond with JSON only."""
