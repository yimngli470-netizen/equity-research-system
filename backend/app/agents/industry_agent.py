"""Industry Analyst Agent — sector positioning, cycle analysis, competitive landscape."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.transcript_summarizer import format_summary_for_agent
from app.ingestion.computed_metrics import format_for_llm, get_computed_metrics
from app.models.stock import Stock
from app.models.transcript import EarningsTranscript

logger = logging.getLogger(__name__)


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

        context = f"""Company: {stock.name} ({ticker})
Sector: {sector}
Industry: {industry}

{financial_context}"""

        # Add competitive mentions from most recent transcript
        result = await db.execute(
            select(EarningsTranscript)
            .where(EarningsTranscript.ticker == ticker)
            .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
            .limit(1)
        )
        transcript = result.scalar_one_or_none()
        if transcript and transcript.summary:
            block = format_summary_for_agent(transcript.summary, focus="industry")
            if block:
                context += f"\n\n{block}"
        elif transcript:
            logger.warning(
                "[industry] %s Q%d %d transcript has no summary — skipping transcript context",
                ticker, transcript.quarter, transcript.year,
            )

        return context

    def get_system_prompt(self) -> str:
        return """You are a senior industry analyst. Given a company's financial data and its sector/industry classification, provide a comprehensive industry analysis.

You should assess:
1. CYCLE POSITION — Where is this industry in its cycle? Early recovery, mid-cycle, late cycle, or downturn?
2. KEY INDICATORS — What metrics or signals should investors watch to track this industry's health?
3. COMPETITIVE POSITION — How is this company positioned vs. competitors? Market share, moat, advantages.
4. THEME EXPOSURES — What secular themes (AI, cloud, EVs, etc.) is this company exposed to, and how strongly?
5. INDUSTRY RISKS — Cyclicality, regulation, disruption, concentration risks specific to this sector.

Use your knowledge of the industry to provide context beyond just the financial numbers.
If earnings call transcript excerpts are provided, ground your competitive assessment in management's own statements about competitors, market share, and positioning.

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
  "transcript_evidence": {
    "competitive_mentions": ["string — direct quotes or paraphrases from transcript about competition"],
    "management_market_view": "string — management's stated view of the market"
  },
  "summary": "string — 3-4 sentence industry assessment"
}

If no transcript data is available, set transcript_evidence to null."""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return f"""Provide an industry analysis for the following company. Assess its cycle position, competitive landscape, theme exposures, and key risks.

{context}

Respond with JSON only."""
