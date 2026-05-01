"""Validation Agent — cross-checks other agents' outputs against hard data.

Runs AFTER all other agents. Uses Sonnet (cheap/fast) to check factual claims
against verified numbers in the database. Catches hallucinated numbers that
could lead to wrong analysis.
"""

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.analysis import AnalysisReport
from app.models.earnings import EarningsEvent
from app.models.estimate import AnalystEstimate
from app.models.financial import Financial
from app.models.valuation import Valuation


class ValidationAgent(BaseAgent):
    agent_type = "validation"
    max_age_days = 1  # always re-run after agents
    model = "claude-sonnet-4-20250514"

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        sections = []

        # Fetch latest agent reports
        agent_reports = {}
        for agent_type in ["news", "earnings", "industry", "valuation"]:
            result = await db.execute(
                select(AnalysisReport)
                .where(
                    AnalysisReport.ticker == ticker,
                    AnalysisReport.agent_type == agent_type,
                )
                .order_by(AnalysisReport.run_date.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row and "error" not in row.report:
                agent_reports[agent_type] = row.report

        if not agent_reports:
            return "No agent reports available to validate."

        # Section 1: Agent claims (summarized for validation)
        sections.append("=== AGENT REPORTS TO VALIDATE ===")
        for agent_type, report in agent_reports.items():
            # Truncate large reports to key fields
            summary = json.dumps(report, indent=2, default=str)
            if len(summary) > 3000:
                summary = summary[:3000] + "\n... (truncated)"
            sections.append(f"\n--- {agent_type.upper()} AGENT ---\n{summary}")

        # Section 2: Hard data from DB
        sections.append("\n=== VERIFIED HARD DATA ===")

        # Latest 4 quarters of financials
        result = await db.execute(
            select(Financial)
            .where(Financial.ticker == ticker)
            .order_by(Financial.period_end_date.desc())
            .limit(4)
        )
        financials = result.scalars().all()
        if financials:
            sections.append("\n--- QUARTERLY FINANCIALS (from DB) ---")
            for f in financials:
                parts = [f"  {f.period} ({f.period_end_date}):"]
                if f.revenue is not None:
                    parts.append(f"Revenue=${f.revenue/1e9:.2f}B")
                if f.net_income is not None:
                    parts.append(f"NI=${f.net_income/1e9:.2f}B")
                if f.eps is not None:
                    parts.append(f"EPS=${f.eps:.2f}")
                if f.gross_profit is not None and f.revenue:
                    parts.append(f"GM={f.gross_profit/f.revenue:.1%}")
                if f.operating_income is not None and f.revenue:
                    parts.append(f"OM={f.operating_income/f.revenue:.1%}")
                if f.free_cash_flow is not None:
                    parts.append(f"FCF=${f.free_cash_flow/1e9:.2f}B")
                sections.append(" ".join(parts))

        # Latest valuation multiples
        result = await db.execute(
            select(Valuation)
            .where(Valuation.ticker == ticker)
            .order_by(Valuation.date.desc())
            .limit(1)
        )
        val = result.scalar_one_or_none()
        if val:
            sections.append("\n--- VALUATION MULTIPLES (from DB) ---")
            lines = []
            if val.forward_pe is not None:
                lines.append(f"  Forward P/E: {val.forward_pe:.1f}")
            if val.trailing_pe is not None:
                lines.append(f"  Trailing P/E: {val.trailing_pe:.1f}")
            if val.peg_ratio is not None:
                lines.append(f"  PEG: {val.peg_ratio:.2f}")
            if val.price_to_sales is not None:
                lines.append(f"  P/S: {val.price_to_sales:.1f}")
            if val.ev_to_ebitda is not None:
                lines.append(f"  EV/EBITDA: {val.ev_to_ebitda:.1f}")
            if val.gross_margins is not None:
                lines.append(f"  Gross Margins: {val.gross_margins:.1%}")
            if val.operating_margins is not None:
                lines.append(f"  Operating Margins: {val.operating_margins:.1%}")
            if val.market_cap is not None:
                lines.append(f"  Market Cap: ${val.market_cap/1e9:.1f}B")
            sections.append("\n".join(lines))

        # Earnings surprises
        result = await db.execute(
            select(EarningsEvent)
            .where(EarningsEvent.ticker == ticker)
            .order_by(EarningsEvent.report_date.desc())
            .limit(4)
        )
        events = result.scalars().all()
        if events:
            sections.append("\n--- EARNINGS SURPRISES (from DB) ---")
            for e in events:
                parts = [f"  {e.report_date}:"]
                if e.eps_actual is not None:
                    parts.append(f"EPS actual=${e.eps_actual:.2f}")
                if e.eps_estimate is not None:
                    parts.append(f"est=${e.eps_estimate:.2f}")
                if e.eps_surprise_pct is not None:
                    parts.append(f"surprise={e.eps_surprise_pct:+.1%}")
                sections.append(" ".join(parts))

        # Analyst estimates
        result = await db.execute(
            select(AnalystEstimate)
            .where(AnalystEstimate.ticker == ticker)
            .order_by(AnalystEstimate.period_end_date.asc())
            .limit(4)
        )
        estimates = result.scalars().all()
        if estimates:
            sections.append("\n--- ANALYST ESTIMATES (from DB) ---")
            for e in estimates:
                parts = [f"  {e.period_end_date}:"]
                if e.eps_consensus is not None:
                    parts.append(f"EPS consensus=${e.eps_consensus:.2f}")
                if e.revenue_consensus is not None:
                    parts.append(f"Rev consensus=${e.revenue_consensus/1e9:.2f}B")
                sections.append(" ".join(parts))

        return "\n".join(sections)

    def get_system_prompt(self) -> str:
        return """You are a fact-checking analyst. Your job is to verify the factual claims made by other AI agents against hard data from the database.

For each agent report, identify quantitative claims (numbers, percentages, trends) and check them against the verified data provided.

For each claim, classify it as:
- CONFIRMED — matches the hard data exactly or very closely
- CLOSE — within 5% of the actual value (rounding differences)
- CONTRADICTED — conflicts with the hard data (include the correct value)
- UNVERIFIABLE — no hard data available to check this claim

Focus on:
1. Revenue, earnings, and margin figures cited by agents
2. Growth rates and trend directions
3. Valuation multiples referenced
4. Forward estimates compared to actual consensus data
5. Any specific dollar amounts or percentages

Do NOT judge opinions, analysis quality, or investment conclusions.
Only flag factual errors — wrong numbers that could lead to wrong analysis.

You must respond with valid JSON only, no other text. Use this exact schema:
{
  "ticker": "string",
  "validation_date": "YYYY-MM-DD",
  "checks": [
    {
      "agent": "news | earnings | industry | valuation",
      "claim": "string — the specific factual claim",
      "data_point": "string — the hard data used to verify",
      "verdict": "CONFIRMED | CLOSE | CONTRADICTED | UNVERIFIABLE",
      "detail": "string — explanation, include correct value if CONTRADICTED"
    }
  ],
  "summary": {
    "total_checks": number,
    "confirmed": number,
    "close": number,
    "contradicted": number,
    "unverifiable": number,
    "reliability_score": 0.0-1.0,
    "flagged_issues": ["string — critical contradictions to highlight"]
  }
}

The reliability_score should be: (confirmed + close) / (confirmed + close + contradicted).
If there are no contradictions, reliability_score = 1.0.
Exclude unverifiable claims from the score calculation."""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return f"""Validate the factual claims in the following agent reports for {ticker} against the verified hard data from the database. Check every quantitative claim you can find.

{context}

Respond with JSON only."""
