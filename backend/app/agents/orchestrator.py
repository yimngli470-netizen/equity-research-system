"""Agent orchestrator — runs all research agents for a ticker."""

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bear_agent import BearAgent
from app.agents.bull_agent import BullAgent
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
# analytical agents (whose reports it reads), and the judge must run AFTER bull and bear (it
# reconciles their cases). Validation always runs last (see run_all_agents).
AGENTS = {
    "news": NewsAgent,
    "earnings": EarningsAgent,
    "industry": IndustryAgent,
    "valuation": ValuationAgent,
    "bull": BullAgent,
    "bear": BearAgent,
    "judge": JudgeAgent,
    "validation": ValidationAgent,
}

# The adversarial dialectic must run in this relative order, after the analytical agents.
_DIALECTIC_ORDER = ["bull", "bear", "judge"]


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


async def _run_single_agent(
    agent_type: str,
    ticker: str,
    force: bool,
) -> AgentResult:
    """Run a single agent with its own DB session."""
    agent_cls = AGENTS[agent_type]
    agent = agent_cls()

    try:
        async with async_session() as db:
            # Check cache first to report whether we used it
            cached = await agent._get_cached(db, ticker)
            if cached and not force:
                return AgentResult(
                    agent_type=agent_type,
                    success=True,
                    report=cached.report,
                    cached=True,
                )

            report = await agent.run(db, ticker, force=force)
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


async def run_all_agents(
    ticker: str,
    agent_types: list[str] | None = None,
    force: bool = False,
) -> OrchestrationResult:
    """Run multiple agents for a ticker.

    Agents run sequentially to avoid rate limit issues with Claude API.
    Each agent has its own DB session for isolation.

    Args:
        ticker: Stock ticker.
        agent_types: Specific agents to run. None = all agents.
        force: Skip cache and re-run all agents.
    """
    requested = set(agent_types or list(AGENTS.keys()))

    # Validate agent types
    for t in requested:
        if t not in AGENTS:
            raise ValueError(f"Unknown agent type: {t}. Available: {list(AGENTS.keys())}")

    # Enforce execution order regardless of how agent_types was passed: analytical agents first
    # (the dialectic reads their reports), then bull → bear → judge, then validation last.
    analytical = [t for t in ("news", "earnings", "industry", "valuation") if t in requested]
    dialectic = [t for t in _DIALECTIC_ORDER if t in requested]
    run_validation = "validation" in requested
    types = analytical + dialectic

    logger.info("Running agents for %s: %s (force=%s)", ticker, types, force)

    result = OrchestrationResult(ticker=ticker)

    for agent_type in types:
        agent_result = await _run_single_agent(agent_type, ticker, force)
        result.results.append(agent_result)

        status = "cached" if agent_result.cached else ("ok" if agent_result.success else "FAILED")
        logger.info(
            "[%s] %s → %s",
            agent_type, ticker, status,
        )

    # Run validation last — always force since it depends on fresh agent outputs
    if run_validation:
        agent_result = await _run_single_agent("validation", ticker, force=True)
        result.results.append(agent_result)
        status = "ok" if agent_result.success else "FAILED"
        logger.info("[validation] %s → %s", ticker, status)

    return result
