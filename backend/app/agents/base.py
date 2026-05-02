"""Base agent class for Claude API-powered research agents.

Each agent:
1. Checks if a cached report exists and is still fresh
2. If fresh, returns the cached report
3. If stale or missing, calls Claude API with structured output
4. Saves the result to analysis_reports table
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.analysis import AnalysisReport

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all research agents."""

    # Subclasses must set these
    agent_type: str = ""  # e.g. "news", "earnings", "industry", "valuation"
    max_age_days: int = 1  # how many days before cache is stale
    model: str = "claude-sonnet-4-20250514"

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def run(
        self,
        db: AsyncSession,
        ticker: str,
        force: bool = False,
    ) -> dict:
        """Run the agent: check cache first, then call Claude if needed.

        Args:
            db: Database session.
            ticker: Stock ticker.
            force: If True, skip cache and always call Claude.

        Returns:
            The analysis report as a dict.
        """
        if not force:
            cached = await self._get_cached(db, ticker)
            if cached is not None:
                logger.info(
                    "[%s] Using cached report for %s (run_date=%s)",
                    self.agent_type, ticker, cached.run_date,
                )
                return cached.report

        logger.info("[%s] Running analysis for %s", self.agent_type, ticker)

        # Build context and prompt
        context = await self.build_context(db, ticker)
        system_prompt = self.get_system_prompt()
        user_prompt = self.get_user_prompt(ticker, context)

        # Anchor the agent in real time so it stops hallucinating "validation_date: 2024-12-19"
        # and so claims about "current" / "latest" data have a concrete reference point.
        user_prompt = f"Today's date is {date.today().isoformat()}.\n\n{user_prompt}"

        # Call Claude API in a thread to avoid blocking the async event loop
        import asyncio
        report = await asyncio.to_thread(self._call_claude, system_prompt, user_prompt)
        report = self.postprocess_report(report, ticker)

        # Save to DB
        await self._save_report(db, ticker, report)

        return report

    @abstractmethod
    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        """Build the data context string that gets injected into the prompt.

        Each agent fetches different data from the DB.
        """
        ...

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt defining the agent's persona and output format."""
        ...

    @abstractmethod
    def get_user_prompt(self, ticker: str, context: str) -> str:
        """Return the user prompt with ticker-specific context."""
        ...

    def postprocess_report(self, report: dict, ticker: str) -> dict:
        """Apply deterministic cleanup before saving an agent report."""
        if "error" not in report:
            report["ticker"] = ticker
        return report

    def _call_claude(self, system_prompt: str, user_prompt: str) -> dict:
        """Call Claude API and parse the JSON response."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            content = response.content[0].text

            # Extract JSON from response (handle markdown code blocks)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            report = json.loads(content.strip())
            logger.info("[%s] Claude API call successful", self.agent_type)
            return report

        except json.JSONDecodeError as e:
            logger.error("[%s] Failed to parse Claude response as JSON: %s", self.agent_type, e)
            return {"error": "Failed to parse response", "raw": content}
        except anthropic.APIError as e:
            logger.error("[%s] Claude API error: %s", self.agent_type, e)
            return {"error": f"API error: {e}"}

    async def _get_cached(self, db: AsyncSession, ticker: str) -> AnalysisReport | None:
        """Check for a fresh cached report."""
        cutoff = date.today() - timedelta(days=self.max_age_days)
        result = await db.execute(
            select(AnalysisReport)
            .where(
                AnalysisReport.ticker == ticker,
                AnalysisReport.agent_type == self.agent_type,
                AnalysisReport.run_date >= cutoff,
            )
            .order_by(AnalysisReport.run_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _save_report(self, db: AsyncSession, ticker: str, report: dict):
        """Save or update the analysis report in the database."""
        # Check for existing report today
        existing = await db.execute(
            select(AnalysisReport).where(
                AnalysisReport.ticker == ticker,
                AnalysisReport.agent_type == self.agent_type,
                AnalysisReport.run_date == date.today(),
            )
        )
        row = existing.scalar_one_or_none()

        if row:
            row.report = report
            row.version += 1
        else:
            db.add(
                AnalysisReport(
                    ticker=ticker,
                    agent_type=self.agent_type,
                    run_date=date.today(),
                    report=report,
                    version=1,
                )
            )

        await db.commit()
        logger.info("[%s] Saved report for %s", self.agent_type, ticker)
