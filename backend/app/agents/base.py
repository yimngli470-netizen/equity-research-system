"""Base agent class for Claude API-powered research agents.

Each agent:
1. Checks the cache (three modes — see `run`)
2. On a hit, returns the cached report
3. Otherwise calls Claude API with structured output
4. Saves the result (+ its input fingerprint) to analysis_reports

Run modes (2026-06-11 smart caching):
- "force": always call the LLM (the old force=True).
- "cache": time-based — reuse a report younger than `max_age_days` (the old force=False).
- "smart": INPUT-based — recompute the agent's input fingerprint (cheap DB reads + prompt hash);
  if it matches the last report's, the inputs haven't changed, so reuse the report regardless of
  age (up to `smart_max_age_days`, a safety ceiling on the LLM's world-knowledge staleness).
  New earnings/transcript/estimates auto-invalidate — this FIXES the documented gotcha where a
  time-based cache could serve a stale earnings report for up to 30 days after a new quarter.
"""

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import date, timedelta

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import LLMUsageLimitError, make_llm_client

# LLMs occasionally emit malformed JSON, and the CLI/API path has transient hiccups; a couple of
# retries absorb those (both NOW's judge and TTD's valuation failed once, then succeeded on re-run).
_MAX_LLM_ATTEMPTS = 3
_RETRY_BACKOFF_S = 2

from app.config import settings
from app.models.analysis import AnalysisReport
from app.models.financial import Financial

logger = logging.getLogger(__name__)


def compare_fingerprints(old: dict | None, new: dict | None,
                         tolerances: dict[str, tuple[str, float]] | None = None) -> bool:
    """True if fingerprints are equivalent. Keys listed in `tolerances` compare numerically with a
    ("rel"|"abs", threshold) band (e.g. price within ±5% ⇒ unchanged); all other keys compare
    exactly. Missing/None fingerprints never match."""
    if not old or not new:
        return False
    if set(old.keys()) != set(new.keys()):
        return False
    tolerances = tolerances or {}
    for k, new_v in new.items():
        old_v = old.get(k)
        if k in tolerances and isinstance(old_v, (int, float)) and isinstance(new_v, (int, float)):
            kind, thr = tolerances[k]
            delta = abs(new_v - old_v)
            if kind == "rel":
                if old_v != 0 and delta / abs(old_v) > thr:
                    return False
                if old_v == 0 and delta > 0:
                    return False
            elif delta > thr:
                return False
        elif old_v != new_v:
            return False
    return True


class BaseAgent(ABC):
    """Abstract base class for all research agents."""

    # Subclasses must set these
    agent_type: str = ""  # e.g. "news", "earnings", "industry", "valuation"
    max_age_days: int = 1  # how many days before the time-based cache is stale
    smart_max_age_days: int = 35  # smart-cache ceiling: re-run even on unchanged inputs after this
    # Numeric fingerprint keys compared with a tolerance band instead of exact equality.
    fingerprint_tolerances: dict[str, tuple[str, float]] = {}
    # Model TIER, not a hardcoded id: "opus" (deep analysis) | "sonnet" (fast). The actual model id
    # is resolved from config (one place to update / an env override) — see Settings.opus_model.
    tier: str = "sonnet"
    # Output token ceiling. The judge/debate emit large structured JSON (bear points, kill-criteria,
    # synthesis, two advocate cases); 4096 truncated them mid-string. A ceiling only caps; you pay for
    # tokens actually generated, so a generous default is free insurance against truncated JSON.
    max_output_tokens: int = 8192

    @property
    def model(self) -> str:
        return settings.opus_model if self.tier == "opus" else settings.sonnet_model

    def __init__(self):
        self.client = make_llm_client()

    async def run(
        self,
        db: AsyncSession,
        ticker: str,
        force: bool = False,
        mode: str | None = None,
    ) -> dict:
        """Run the agent: check cache per `mode`, then call Claude if needed.

        Args:
            db: Database session.
            ticker: Stock ticker.
            force: Legacy flag — force=True ⇒ mode "force", else "cache" (ignored if mode given).
            mode: "force" | "cache" | "smart" (see module docstring).

        Returns:
            The analysis report as a dict.
        """
        mode = mode or ("force" if force else "cache")

        fingerprint: dict | None = None
        if mode == "smart":
            fingerprint = await self._full_fingerprint(db, ticker)
            cached = await self._get_smart_cached(db, ticker, fingerprint)
            if cached is not None:
                logger.info("[%s] %s: inputs unchanged since %s — smart-cache hit (no LLM)",
                            self.agent_type, ticker, cached.run_date)
                return cached.report
        elif mode == "cache":
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
        user_prompt = await self._augment_user_prompt(db, ticker, user_prompt)

        # Call Claude API in a thread to avoid blocking the async event loop
        import asyncio
        report = await asyncio.to_thread(self._call_claude, system_prompt, user_prompt)
        report = self.postprocess_report(report, ticker)

        # Save to DB with the input fingerprint (compute it if we didn't already).
        if fingerprint is None:
            fingerprint = await self._full_fingerprint(db, ticker)
        await self._save_report(db, ticker, report, fingerprint=fingerprint)

        return report

    # ── Smart cache (input fingerprints) ─────────────────────────────────────

    async def compute_fingerprint(self, db: AsyncSession, ticker: str) -> dict | None:
        """A deterministic snapshot of the DATA this agent's context is built from (cheap DB reads,
        no LLM). None = this agent doesn't support smart caching (smart mode then always runs).
        Subclasses override; the prompt hash is appended automatically."""
        return None

    async def _full_fingerprint(self, db: AsyncSession, ticker: str) -> dict | None:
        """Agent's data fingerprint + a hash of the system prompt, so ANY prompt/schema change
        auto-invalidates every cached report generated under the old prompt."""
        fp = await self.compute_fingerprint(db, ticker)
        if fp is None:
            return None
        fp = dict(fp)
        fp["prompt"] = hashlib.sha256(self.get_system_prompt().encode()).hexdigest()[:12]
        return fp

    async def _get_smart_cached(
        self, db: AsyncSession, ticker: str, fingerprint: dict | None
    ) -> AnalysisReport | None:
        """Latest report if its stored fingerprint matches the current one (within tolerances) and
        it's younger than the smart ceiling. None ⇒ caller must run the LLM."""
        if fingerprint is None:
            return None
        row = (
            await db.execute(
                select(AnalysisReport)
                .where(AnalysisReport.ticker == ticker, AnalysisReport.agent_type == self.agent_type)
                .order_by(AnalysisReport.run_date.desc(), AnalysisReport.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not row or not isinstance(row.report, dict) or "error" in row.report:
            return None
        if (date.today() - row.run_date).days > self.smart_max_age_days:
            return None
        if not compare_fingerprints(row.input_fingerprint, fingerprint, self.fingerprint_tolerances):
            return None
        return row

    async def _augment_user_prompt(self, db: AsyncSession, ticker: str, user_prompt: str) -> str:
        """Prepend deterministic, real-time anchors to a user prompt (shared by all agents and the
        bull/bear debate): today's date, a just-reported-quarter marker, and stale-data warnings.
        Pure code, no LLM — keeps agents from narrating stale data as 'current'."""
        # Anchor the agent in real time so it stops hallucinating "validation_date: 2024-12-19"
        # and so claims about "current" / "latest" data have a concrete reference point.
        prefix_parts = [f"Today's date is {date.today().isoformat()}."]

        # If a quarter was reported in the last 90 days, surface it so agents anchor
        # their analysis on the just-released quarter instead of the prior one.
        recency = await self._get_recency_marker(db, ticker)
        if recency:
            prefix_parts.append(recency)

        # Deterministic data freshness warnings — prevents agents from calling
        # stale data current. Pure code (no LLM); only emits when something is
        # actually stale.
        from app.data_freshness import build_freshness_report, format_freshness_warnings
        try:
            freshness_report = await build_freshness_report(db, ticker)
            warnings = format_freshness_warnings(freshness_report)
            if warnings:
                stale_cats = [
                    name for name, c in freshness_report.categories.items()
                    if c.status.value in ("stale", "missing")
                ]
                logger.info(
                    "[%s] %s freshness: injecting warnings for %s",
                    self.agent_type, ticker, ", ".join(stale_cats),
                )
                prefix_parts.append(warnings)
        except Exception:
            logger.exception("[%s] freshness check failed for %s", self.agent_type, ticker)

        return "\n\n".join(prefix_parts) + f"\n\n{user_prompt}"

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
        """Call Claude and parse the JSON response, retrying transient failures.

        Malformed-JSON and transient CLI/API errors are retried (the model re-rolls and usually
        returns clean JSON the next time). A usage-limit error is NOT retried — it propagates so the
        orchestrator can stop the run and resume later via smart-cache.
        """
        last_err: Exception | None = None
        content: str | None = None
        for attempt in range(1, _MAX_LLM_ATTEMPTS + 1):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_output_tokens,
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
                if attempt > 1:
                    logger.info("[%s] Claude call succeeded on attempt %d", self.agent_type, attempt)
                else:
                    logger.info("[%s] Claude API call successful", self.agent_type)
                return report

            except LLMUsageLimitError:
                raise  # don't retry a usage limit — let the orchestrator stop + resume
            except (json.JSONDecodeError, anthropic.APIError, RuntimeError) as e:
                last_err = e
                logger.warning("[%s] LLM attempt %d/%d failed (%s): %s",
                               self.agent_type, attempt, _MAX_LLM_ATTEMPTS, type(e).__name__, str(e)[:160])
                if attempt < _MAX_LLM_ATTEMPTS:
                    time.sleep(_RETRY_BACKOFF_S * attempt)

        logger.error("[%s] all %d LLM attempts failed: %s", self.agent_type, _MAX_LLM_ATTEMPTS, last_err)
        if isinstance(last_err, json.JSONDecodeError):
            return {"error": "Failed to parse response", "raw": content}
        return {"error": f"LLM call failed: {last_err}"}

    async def _get_recency_marker(self, db: AsyncSession, ticker: str) -> str | None:
        """Return a one-line marker if the ticker just reported earnings.

        Anchors agents on the freshly-released quarter so they don't keep
        narrating about the prior quarter even when newer data is available.
        """
        result = await db.execute(
            select(Financial)
            .where(Financial.ticker == ticker)
            .order_by(Financial.period_end_date.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if not latest:
            return None
        days_old = (date.today() - latest.period_end_date).days
        if days_old < 0 or days_old > 90:
            return None
        return (
            f"NOTE: {ticker}'s most recently reported quarter is {latest.period} "
            f"(ended {latest.period_end_date}, {days_old} days ago). "
            f"Anchor your analysis on THIS quarter — discuss what changed in {latest.period} "
            f"vs prior quarters, not just trailing trends."
        )

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

    async def _save_report(self, db: AsyncSession, ticker: str, report: dict,
                           fingerprint: dict | None = None):
        """Save or update this agent's report in the database."""
        await self._save_report_as(db, ticker, self.agent_type, report, fingerprint=fingerprint)

    async def _save_report_as(self, db: AsyncSession, ticker: str, agent_type: str, report: dict,
                              fingerprint: dict | None = None):
        """Upsert an analysis report under an explicit agent_type. Lets one LLM call persist more
        than one report row (e.g. the bull/bear debate writes both `bull` and `bear` from one call)."""
        existing = await db.execute(
            select(AnalysisReport).where(
                AnalysisReport.ticker == ticker,
                AnalysisReport.agent_type == agent_type,
                AnalysisReport.run_date == date.today(),
            )
        )
        row = existing.scalar_one_or_none()

        if row:
            row.report = report
            row.version += 1
            row.input_fingerprint = fingerprint
        else:
            db.add(
                AnalysisReport(
                    ticker=ticker,
                    agent_type=agent_type,
                    run_date=date.today(),
                    report=report,
                    version=1,
                    input_fingerprint=fingerprint,
                )
            )

        await db.commit()
        logger.info("[%s] Saved report for %s", agent_type, ticker)
