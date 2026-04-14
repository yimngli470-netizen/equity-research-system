"""News Analyst Agent — analyzes recent news for impact and sentiment."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.document import Document


class NewsAgent(BaseAgent):
    agent_type = "news"
    max_age_days = 1  # refresh daily

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        cutoff = date.today() - timedelta(days=14)
        result = await db.execute(
            select(Document)
            .where(
                Document.ticker == ticker,
                Document.doc_type == "news",
                Document.date >= cutoff,
            )
            .order_by(Document.date.desc())
            .limit(20)
        )
        articles = result.scalars().all()

        if not articles:
            return "No recent news articles found."

        lines = [f"=== Recent News for {ticker} (last 14 days) ===\n"]
        for i, a in enumerate(articles, 1):
            lines.append(f"[{i}] Date: {a.date}")
            lines.append(f"    Title: {a.title}")
            lines.append(f"    Content: {a.content[:500]}")
            lines.append("")

        return "\n".join(lines)

    def get_system_prompt(self) -> str:
        return """You are a senior financial news analyst. Your job is to analyze recent news about a stock and extract factual, actionable insights.

Focus on FACTS, not opinions. For each significant news item:
- What happened (the fact)
- Which part of the business it affects (revenue, margins, competition, regulatory, macro)
- How significant it is (impact score 0.0-1.0)
- Whether it's positive, negative, or neutral for the stock

You must respond with valid JSON only, no other text. Use this exact schema:
{
  "ticker": "string",
  "analysis_date": "YYYY-MM-DD",
  "items": [
    {
      "headline": "string",
      "fact_summary": "string — one sentence of what actually happened",
      "impact_category": "revenue | margin | competition | regulatory | macro | product | partnership",
      "impact_score": 0.0-1.0,
      "impact_direction": "positive | negative | neutral",
      "reasoning": "string — why this matters for the company",
      "time_horizon": "short_term | medium_term | long_term"
    }
  ],
  "overall_sentiment": -1.0 to 1.0,
  "key_themes": ["string"],
  "summary": "string — 2-3 sentence overall assessment"
}"""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return f"""Analyze the following recent news for {ticker}. Focus only on facts that could materially impact the stock. Ignore opinion pieces, listicles, and generic market commentary. If a news item is not specifically about {ticker}, skip it.

{context}

Respond with JSON only."""
