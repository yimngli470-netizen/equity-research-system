"""Earnings Analyst Agent — deep dive into quarterly results and trends."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.ingestion.computed_metrics import format_for_llm, get_computed_metrics


class EarningsAgent(BaseAgent):
    agent_type = "earnings"
    max_age_days = 30  # refresh monthly or when new quarter drops

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        snapshot = await get_computed_metrics(db, ticker)
        return format_for_llm(snapshot)

    def get_system_prompt(self) -> str:
        return """You are a senior equity research analyst specializing in earnings analysis. Given a company's quarterly financial data with computed growth rates and margins, provide a deep analytical assessment.

Focus on:
1. KEY DRIVERS — What drove the quarter's results? Revenue acceleration/deceleration, margin expansion/contraction, and why.
2. TREND ANALYSIS — Are growth rates improving or deteriorating? Are margins expanding sustainably?
3. EARNINGS QUALITY — Is growth driven by real demand or one-time items? Is FCF tracking net income?
4. RISKS — What could go wrong? Margin pressure, growth deceleration, competitive threats evident in the numbers.
5. FORWARD OUTLOOK — Based on trends, what should we expect next quarter?

You must respond with valid JSON only, no other text. Use this exact schema:
{
  "ticker": "string",
  "latest_quarter": "string",
  "headline_assessment": "string — one sentence summary",
  "key_drivers": [
    {
      "driver": "string",
      "impact": "strong_positive | positive | neutral | negative | strong_negative",
      "detail": "string"
    }
  ],
  "trend_analysis": {
    "revenue_trend": "accelerating | stable | decelerating",
    "margin_trend": "expanding | stable | compressing",
    "earnings_quality": "high | moderate | low",
    "detail": "string — 2-3 sentences on the overall trajectory"
  },
  "risks": [
    {
      "risk": "string",
      "severity": 0.0-1.0,
      "detail": "string"
    }
  ],
  "forward_outlook": {
    "revenue_direction": "accelerating | stable | decelerating",
    "margin_direction": "expanding | stable | compressing",
    "confidence": "high | moderate | low",
    "detail": "string"
  },
  "earnings_quality_score": 0.0-1.0,
  "summary": "string — 3-4 sentence comprehensive assessment"
}"""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return f"""Analyze the following financial data for {ticker}. Provide a deep earnings analysis covering key drivers, trends, quality, risks, and forward outlook.

{context}

Respond with JSON only."""
