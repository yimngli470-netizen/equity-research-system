"""Valuation Analyst Agent — multiples analysis, DCF assessment, target price range."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.ingestion.computed_metrics import format_for_llm, get_computed_metrics


class ValuationAgent(BaseAgent):
    agent_type = "valuation"
    max_age_days = 7  # refresh weekly

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        snapshot = await get_computed_metrics(db, ticker)
        return format_for_llm(snapshot)

    def get_system_prompt(self) -> str:
        return """You are a senior valuation analyst. Given a company's financial data, growth rates, and current valuation multiples, provide a comprehensive valuation assessment.

You should assess:
1. MULTIPLES ANALYSIS — Are current P/E, P/S, EV/EBITDA multiples justified by growth? Compare to historical and peer ranges.
2. GROWTH-ADJUSTED VALUE — PEG ratio interpretation. Is the market fairly pricing the growth?
3. DCF FRAMEWORK — Provide a simplified DCF assessment with your assumptions for revenue growth (5 years), terminal growth, FCF margin, and WACC. Calculate bull/base/bear intrinsic values.
4. TARGET PRICE RANGE — Based on multiples and DCF, what's a reasonable price range?
5. VALUATION VERDICT — Is the stock undervalued, fairly valued, or overvalued at current prices?

Be specific with numbers. Use the actual financial data provided to justify your assumptions.

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
  "summary": "string — 3-4 sentence valuation assessment"
}"""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return f"""Provide a comprehensive valuation analysis for {ticker}. Assess multiples, run a simplified DCF, and determine a target price range.

{context}

Respond with JSON only."""
