"""Earnings Analyst Agent — deep dive into quarterly results and trends."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.transcript_summarizer import format_summary_for_agent
from app.ingestion.computed_metrics import format_for_llm, get_computed_metrics
from app.models.earnings import EarningsEvent
from app.models.transcript import EarningsTranscript

logger = logging.getLogger(__name__)


class EarningsAgent(BaseAgent):
    agent_type = "earnings"
    max_age_days = 30  # refresh monthly or when new quarter drops
    model = "claude-opus-4-20250514"

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        snapshot = await get_computed_metrics(db, ticker)
        context = format_for_llm(snapshot)

        # Add earnings transcript (most recent quarter)
        result = await db.execute(
            select(EarningsTranscript)
            .where(EarningsTranscript.ticker == ticker)
            .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
            .limit(1)
        )
        transcript = result.scalar_one_or_none()
        if transcript and transcript.summary:
            block = format_summary_for_agent(transcript.summary, focus="earnings")
            if block:
                context += (
                    f"\n\n--- EARNINGS CALL (Q{transcript.quarter} {transcript.year}) ---\n"
                    f"{block}"
                )
        elif transcript:
            # Latest transcript exists but summarizer didn't produce output
            # (transient API/parse failure). Skip transcript context for this run
            # rather than feeding stale or low-quality data to the agent.
            logger.warning(
                "[earnings] %s Q%d %d transcript has no summary — skipping transcript context",
                ticker, transcript.quarter, transcript.year,
            )

        # Add beat/miss history (last 4 quarters)
        result = await db.execute(
            select(EarningsEvent)
            .where(EarningsEvent.ticker == ticker)
            .order_by(EarningsEvent.report_date.desc())
            .limit(4)
        )
        events = result.scalars().all()
        if events:
            lines = ["--- EARNINGS SURPRISE HISTORY ---"]
            for e in events:
                beat = ""
                if e.eps_actual is not None and e.eps_estimate is not None:
                    diff = e.eps_actual - e.eps_estimate
                    beat = f"{'beat' if diff >= 0 else 'miss'} by ${abs(diff):.2f}"
                    if e.eps_surprise_pct is not None:
                        beat += f" ({e.eps_surprise_pct:+.1%})"
                lines.append(f"  {e.report_date}: EPS actual={e.eps_actual}, est={e.eps_estimate} → {beat}")
            context += "\n\n" + "\n".join(lines)

        return context

    def get_system_prompt(self) -> str:
        return """You are a senior equity research analyst specializing in earnings analysis. Given a company's quarterly financial data, earnings call transcript excerpts, and beat/miss history, provide a deep analytical assessment.

Focus on:
1. KEY DRIVERS — What drove the quarter's results? Revenue acceleration/deceleration, margin expansion/contraction, and why.
2. TREND ANALYSIS — Are growth rates improving or deteriorating? Are margins expanding sustainably?
3. EARNINGS QUALITY — Is growth driven by real demand or one-time items? Is FCF tracking net income?
4. RISKS — What could go wrong? Margin pressure, growth deceleration, competitive threats evident in the numbers.
5. FORWARD OUTLOOK — Based on trends and management guidance, what should we expect next quarter?
6. TRANSCRIPT ANALYSIS — If transcript data is provided, analyze management tone, segment-level detail, one-time items mentioned, key analyst concerns from Q&A, and forward guidance specifics.

IMPORTANT: Use ONLY the numbers and facts provided in the data. Do not fabricate or estimate numbers not present in the input. When citing transcript content, stay faithful to what management actually said.

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
  "transcript_analysis": {
    "management_tone": "confident | cautious | defensive | evasive",
    "key_themes_from_call": ["string"],
    "one_time_items": ["string — description of any non-recurring items mentioned"],
    "segment_highlights": ["string — segment-level performance details"],
    "analyst_concerns": ["string — key concerns raised in Q&A"],
    "forward_guidance_detail": "string — specific guidance given by management"
  },
  "beat_miss_history": {
    "last_4q_eps_beats": 0-4,
    "avg_surprise_pct": number,
    "trend": "improving | stable | deteriorating"
  },
  "earnings_quality_score": 0.0-1.0,
  "summary": "string — 3-4 sentence comprehensive assessment"
}

If no transcript data is available, set transcript_analysis fields to null.
If no beat/miss history is available, set beat_miss_history fields to null."""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return f"""Analyze the following financial data for {ticker}. Provide a deep earnings analysis covering key drivers, trends, quality, risks, and forward outlook. If earnings call transcript excerpts are included, analyze management commentary, segment details, and analyst concerns.

{context}

Respond with JSON only."""
