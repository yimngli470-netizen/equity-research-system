"""Industry Analyst Agent — sector positioning, cycle analysis, competitive landscape."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.ingestion.computed_metrics import format_for_llm, get_computed_metrics
from app.models.stock import Stock


class IndustryAgent(BaseAgent):
    agent_type = "industry"
    max_age_days = 7  # refresh weekly
    model = "claude-opus-4-20250514"

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        # Get the stock's sector/industry info
        stock = await db.get(Stock, ticker)
        sector = stock.sector or "Unknown"
        industry = stock.industry or "Unknown"

        # Get the company's financial context
        snapshot = await get_computed_metrics(db, ticker)
        financial_context = format_for_llm(snapshot)

        return f"""Company: {stock.name} ({ticker})
Sector: {sector}
Industry: {industry}

{financial_context}"""

    def get_system_prompt(self) -> str:
        return """You are a senior industry analyst. Given a company's financial data and its sector/industry classification, provide a comprehensive industry analysis.

You should assess:
1. CYCLE POSITION — Where is this industry in its cycle? Early recovery, mid-cycle, late cycle, or downturn?
2. KEY INDICATORS — What metrics or signals should investors watch to track this industry's health?
3. COMPETITIVE POSITION — How is this company positioned vs. competitors? Market share, moat, advantages.
4. THEME EXPOSURES — What secular themes (AI, cloud, EVs, etc.) is this company exposed to, and how strongly?
5. INDUSTRY RISKS — Cyclicality, regulation, disruption, concentration risks specific to this sector.

Use your knowledge of the industry to provide context beyond just the financial numbers.

You must respond with valid JSON only, no other text. Use this exact schema:
{
  "ticker": "string",
  "sector": "string",
  "industry": "string",
  "cycle_position": "early_recovery | mid_cycle | late_cycle | downturn",
  "cycle_assessment": "string — 2-3 sentences explaining the cycle position",
  "key_indicators": [
    {
      "indicator": "string",
      "current_reading": "string",
      "signal": "bullish | neutral | bearish"
    }
  ],
  "competitive_position": {
    "market_share_trend": "gaining | stable | losing",
    "moat_strength": "strong | moderate | weak",
    "key_advantages": ["string"],
    "key_competitors": ["string"],
    "competitive_risks": ["string"]
  },
  "theme_exposures": [
    {
      "theme": "string",
      "exposure_score": 0.0-1.0,
      "reasoning": "string"
    }
  ],
  "industry_risks": [
    {
      "risk": "string",
      "severity": 0.0-1.0,
      "detail": "string"
    }
  ],
  "summary": "string — 3-4 sentence industry assessment"
}"""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return f"""Provide an industry analysis for the following company. Assess its cycle position, competitive landscape, theme exposures, and key risks.

{context}

Respond with JSON only."""
