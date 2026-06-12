"""Validation Agent — cross-checks other agents' outputs against hard data.

Runs AFTER all other agents. As of 2026-06-09 it is **deterministic-only** (no LLM call): the pure
-Python `deterministic_validator` re-derives every numeric claim (P/E multiples, current price,
quarter-specific revenue/EPS) against the DB with hard tolerances and produces the `checks` +
`reliability_score` the decision gate and AI-feature extractor consume.

Why we dropped the LLM (Sonnet) semantic pass: in practice it confirmed ~95% of claims and almost
never lowered reliability below the gate threshold — paying a Claude call for an auditor that rarely
changed the outcome. The deterministic checks catch the genuinely dangerous thing (hallucinated
numbers) for free, every run. The judge (2.1) already does the cross-agent / tone cross-examination
the semantic pass duplicated. The class keeps its `agent_type`, report shape, and gate wiring so
nothing downstream changes — only the LLM call is gone.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.decision.deterministic_validator import run_deterministic_validation
from app.models.analysis import AnalysisReport

logger = logging.getLogger(__name__)


class ValidationAgent(BaseAgent):
    agent_type = "validation"
    max_age_days = 1  # always re-run after agents

    def __init__(self):
        # Deterministic-only: deliberately skip BaseAgent.__init__ (no Anthropic client needed, so
        # validation runs even without an API key).
        self._deterministic_checks: list[dict] = []

    async def run(self, db: AsyncSession, ticker: str, force: bool = False,
                  mode: str | None = None) -> dict:
        """Deterministic-only validation — no LLM call, so `mode` is irrelevant: always re-runs
        (free) against freshly-ingested data. (Overrides BaseAgent.run, which would call Claude.)"""
        agent_reports = await self._fetch_agent_reports(db, ticker)
        if not agent_reports:
            report = self.postprocess_report({"checks": []}, ticker)
            await self._save_report(db, ticker, report)
            return report

        det_checks = await run_deterministic_validation(db, ticker, agent_reports)
        self._deterministic_checks = [c.to_dict() for c in det_checks]
        logger.info(
            "[validation] %s: %d deterministic checks (%d confirmed, %d close, %d contradicted)",
            ticker, len(det_checks),
            sum(1 for c in det_checks if c.verdict == "CONFIRMED"),
            sum(1 for c in det_checks if c.verdict == "CLOSE"),
            sum(1 for c in det_checks if c.verdict == "CONTRADICTED"),
        )
        # No semantic checks — postprocess merges the stashed deterministic ones + recomputes summary.
        report = self.postprocess_report({"checks": []}, ticker)
        await self._save_report(db, ticker, report)
        return report

    async def _fetch_agent_reports(self, db: AsyncSession, ticker: str) -> dict:
        """Latest non-error analytical reports — the claims the deterministic validator checks."""
        agent_reports: dict = {}
        for agent_type in ["news", "earnings", "industry", "valuation"]:
            row = (
                await db.execute(
                    select(AnalysisReport)
                    .where(AnalysisReport.ticker == ticker, AnalysisReport.agent_type == agent_type)
                    .order_by(AnalysisReport.run_date.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row and isinstance(row.report, dict) and "error" not in row.report:
                agent_reports[agent_type] = row.report
        return agent_reports

    def postprocess_report(self, report: dict, ticker: str) -> dict:
        """Keep validation identity deterministic, and merge deterministic
        numeric checks (run in build_context) with the LLM's semantic checks.
        """
        if "error" in report:
            return report
        report["ticker"] = ticker
        report["validation_date"] = date.today().isoformat()

        # The LLM's semantic checks
        semantic_checks = report.get("checks", [])
        if not isinstance(semantic_checks, list):
            semantic_checks = []
        for c in semantic_checks:
            if isinstance(c, dict):
                c.setdefault("source", "semantic")

        # Merge in deterministic checks (computed in build_context, stashed)
        all_checks = list(semantic_checks) + list(self._deterministic_checks)
        report["checks"] = all_checks

        # Recompute summary across both sources
        counts = {"confirmed": 0, "close": 0, "contradicted": 0, "unverifiable": 0}
        flagged_issues = []
        det_counts = {"confirmed": 0, "close": 0, "contradicted": 0, "unverifiable": 0}
        sem_counts = {"confirmed": 0, "close": 0, "contradicted": 0, "unverifiable": 0}

        for check in all_checks:
            if not isinstance(check, dict):
                continue
            verdict = str(check.get("verdict", "")).upper()
            key = verdict.lower()
            if key in counts:
                counts[key] += 1
            source = check.get("source", "semantic")
            target = det_counts if source == "deterministic" else sem_counts
            if key in target:
                target[key] += 1
            if verdict == "CONTRADICTED":
                claim = check.get("claim", "Unknown claim")
                detail = check.get("detail", "")
                flagged_issues.append(f"{claim}: {detail}")

        total = sum(counts.values())
        reliability = (
            (counts["confirmed"] + 0.5 * counts["close"]) / total if total else 0.0
        )
        report["summary"] = {
            "total_checks": total,
            **counts,
            "deterministic": det_counts,
            "semantic": sem_counts,
            "reliability_score": round(reliability, 3),
            "flagged_issues": flagged_issues,
        }
        # Clear stash so a re-run doesn't double-count
        self._deterministic_checks = []
        return report

    # ── ABC stubs ───────────────────────────────────────────────────────────
    # Validation is deterministic-only (see `run`); these satisfy the BaseAgent ABC but are unused —
    # there is no LLM call, so there is no context or prompt to build.
    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        return ""

    def get_system_prompt(self) -> str:
        return ""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return ""
