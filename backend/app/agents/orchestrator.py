"""Agent orchestrator — runs all research agents for a ticker."""

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.debate import DebateAgent
from app.agents.earnings_agent import EarningsAgent
from app.agents.industry_agent import IndustryAgent
from app.agents.judge_agent import JudgeAgent
from app.agents.news_agent import NewsAgent
from app.agents.validation_agent import ValidationAgent
from app.agents.valuation_agent import ValuationAgent
from app.database import async_session

logger = logging.getLogger(__name__)

# Agent registry. ORDER MATTERS — agents run sequentially in this order, each committing before the
# next. The bull/bear/judge dialectic (roadmap 2.1) is a synthesis layer: it must run AFTER the four
# analytical agents (whose reports it reads). Bull and bear come from ONE Opus call (`DebateAgent`,
# which writes both `bull` and `bear` rows), then the judge reconciles them. Validation runs last and
# is deterministic-only (no LLM). Note: "bull"/"bear" are produced by the debate step, not the
# registry — see run_all_agents.
AGENTS = {
    "news": NewsAgent,
    "earnings": EarningsAgent,
    "industry": IndustryAgent,
    "valuation": ValuationAgent,
    "judge": JudgeAgent,
    "validation": ValidationAgent,
}


@dataclass
class AgentResult:
    agent_type: str
    success: bool
    report: dict | None = None
    error: str | None = None
    cached: bool = False


@dataclass
class OrchestrationResult:
    ticker: str
    results: list[AgentResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(r.success for r in self.results)


# Every pipeline step in canonical run order. bull+bear come from the single debate call.
_ALL_STEPS = ["news", "earnings", "industry", "valuation", "bull", "bear", "judge", "validation"]
_ANALYTICAL = ["news", "earnings", "industry", "valuation"]


async def _run_single_agent(
    agent_type: str,
    ticker: str,
    mode: str,
) -> AgentResult:
    """Run a single agent with its own DB session."""
    agent_cls = AGENTS[agent_type]
    agent = agent_cls()

    try:
        async with async_session() as db:
            # Pre-check the cache so the result reports whether it was used (run() re-checks; the
            # duplicate check is a few indexed reads).
            cached = None
            if mode == "cache":
                cached = await agent._get_cached(db, ticker)
            elif mode == "smart":
                fp = await agent._full_fingerprint(db, ticker)
                cached = await agent._get_smart_cached(db, ticker, fp)
            if cached is not None:
                return AgentResult(
                    agent_type=agent_type,
                    success=True,
                    report=cached.report,
                    cached=True,
                )

            report = await agent.run(db, ticker, mode=mode)
            return AgentResult(
                agent_type=agent_type,
                success="error" not in report,
                report=report,
                cached=False,
            )
    except Exception as e:
        logger.exception("[%s] Agent failed for %s", agent_type, ticker)
        return AgentResult(
            agent_type=agent_type,
            success=False,
            error=str(e),
        )


async def _run_debate(ticker: str, mode: str) -> list[AgentResult]:
    """One Opus call → both the bull and bear rows. Returns an AgentResult for each side."""
    from app.agents.debate import DebateAgent

    try:
        async with async_session() as db:
            pair = await DebateAgent().run(db, ticker, mode=mode)
        was_cached = bool(pair.get("cached"))
        return [
            AgentResult(agent_type=side, success="error" not in rep, report=rep, cached=was_cached)
            for side, rep in (("bull", pair["bull"]), ("bear", pair["bear"]))
        ]
    except Exception as e:
        logger.exception("[debate] failed for %s", ticker)
        return [AgentResult(agent_type=s, success=False, error=str(e)) for s in ("bull", "bear")]


async def run_all_agents(
    ticker: str,
    agent_types: list[str] | None = None,
    force: bool = False,
    mode: str | None = None,
) -> OrchestrationResult:
    """Run multiple agents for a ticker.

    Agents run sequentially to avoid rate limit issues with Claude API.
    Each agent has its own DB session for isolation.

    Args:
        ticker: Stock ticker.
        agent_types: Specific agents to run. None = all agents.
        force: Legacy flag — True ⇒ mode "force", else "cache" (ignored if mode given).
        mode: "force" | "cache" | "smart" — smart re-runs an agent only when its INPUTS changed
            (new filing/transcript/estimates/material news), so a quiet-day pipeline run costs
            ~0 LLM calls while scoring/decision still recompute fresh.
    """
    mode = mode or ("force" if force else "cache")
    requested = set(agent_types or _ALL_STEPS)

    # Validate requested steps
    for t in requested:
        if t not in _ALL_STEPS:
            raise ValueError(f"Unknown agent type: {t}. Available: {_ALL_STEPS}")

    # Enforce execution order regardless of how agent_types was passed: analytical agents first (the
    # dialectic reads their reports), then the bull/bear debate (one call), then the judge, then
    # validation (deterministic, depends on fresh agent outputs).
    analytical = [t for t in _ANALYTICAL if t in requested]
    run_debate = ("bull" in requested) or ("bear" in requested)
    run_judge = "judge" in requested
    run_validation = "validation" in requested

    logger.info("Running for %s: analytical=%s debate=%s judge=%s validation=%s (mode=%s)",
                ticker, analytical, run_debate, run_judge, run_validation, mode)

    result = OrchestrationResult(ticker=ticker)

    for agent_type in analytical:
        agent_result = await _run_single_agent(agent_type, ticker, mode)
        result.results.append(agent_result)
        status = "cached" if agent_result.cached else ("ok" if agent_result.success else "FAILED")
        logger.info("[%s] %s → %s", agent_type, ticker, status)

    if run_debate:
        for agent_result in await _run_debate(ticker, mode):
            result.results.append(agent_result)
            status = "cached" if agent_result.cached else ("ok" if agent_result.success else "FAILED")
            logger.info("[%s] %s → %s", agent_result.agent_type, ticker, status)

    if run_judge:
        agent_result = await _run_single_agent("judge", ticker, mode)
        result.results.append(agent_result)
        status = "cached" if agent_result.cached else ("ok" if agent_result.success else "FAILED")
        logger.info("[judge] %s → %s", ticker, status)

    # Run validation last — always force: it's deterministic (no LLM), so it's free to re-verify
    # the (possibly cached) reports against the freshly-ingested data every run.
    if run_validation:
        agent_result = await _run_single_agent("validation", ticker, mode="force")
        result.results.append(agent_result)
        logger.info("[validation] %s → %s", ticker, "ok" if agent_result.success else "FAILED")

    return result
