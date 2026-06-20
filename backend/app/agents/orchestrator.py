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
from app.llm import LLMUsageLimitError

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
    usage_limited: bool = False  # failed specifically because the subscription limit was hit


@dataclass
class OrchestrationResult:
    ticker: str
    results: list[AgentResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(r.success for r in self.results)


# Every pipeline step in canonical run order. bull+bear come from the single debate call;
# "forecast" (4.2) runs FIRST — the valuation agent reads our model's numbers.
_ALL_STEPS = ["forecast", "news", "earnings", "industry", "valuation", "bull", "bear", "judge", "validation"]
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
    except LLMUsageLimitError as e:
        logger.warning("[%s] subscription usage limit hit for %s", agent_type, ticker)
        return AgentResult(agent_type=agent_type, success=False, error=str(e), usage_limited=True)
    except Exception as e:
        logger.exception("[%s] Agent failed for %s", agent_type, ticker)
        return AgentResult(
            agent_type=agent_type,
            success=False,
            error=str(e),
        )


async def _run_forecast(ticker: str, mode: str) -> AgentResult:
    """The driver-based forecast (4.2): one smart-cached Opus call → the `forecasts` row the
    valuation agent (and later the DCF) consume. Thin history degrades to a clean no-op."""
    from app.forecast.engine import ensure_forecast, summarize_forecast

    try:
        async with async_session() as db:
            row, cached = await ensure_forecast(db, ticker, mode=mode if mode != "cache" else "smart")
        if row is None:
            return AgentResult(agent_type="forecast", success=True,
                               report={"skipped": "history too thin to model"}, cached=False)
        return AgentResult(
            agent_type="forecast",
            success=True,
            report={"as_of": row.as_of.isoformat(), "base_ntm_eps": row.base_ntm_eps,
                    "base_next_q_eps": row.base_next_q_eps,
                    "eps_vs_street_next_q": row.eps_vs_street_next_q,
                    "summary": summarize_forecast(row)},
            cached=cached,
        )
    except LLMUsageLimitError as e:
        logger.warning("[forecast] subscription usage limit hit for %s", ticker)
        return AgentResult(agent_type="forecast", success=False, error=str(e), usage_limited=True)
    except Exception as e:
        logger.exception("[forecast] failed for %s", ticker)
        return AgentResult(agent_type="forecast", success=False, error=str(e))


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
    except LLMUsageLimitError as e:
        logger.warning("[debate] subscription usage limit hit for %s", ticker)
        return [AgentResult(agent_type=s, success=False, error=str(e), usage_limited=True)
                for s in ("bull", "bear")]
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
    run_forecast = "forecast" in requested
    run_debate = ("bull" in requested) or ("bear" in requested)
    run_judge = "judge" in requested
    run_validation = "validation" in requested

    logger.info("Running for %s: forecast=%s analytical=%s debate=%s judge=%s validation=%s (mode=%s)",
                ticker, run_forecast, analytical, run_debate, run_judge, run_validation, mode)

    result = OrchestrationResult(ticker=ticker)

    # Total LLM steps (validation is deterministic, no LLM) — used to report "X/N done" on a limit.
    total_llm = ((1 if run_forecast else 0) + len(analytical)
                 + (2 if run_debate else 0) + (1 if run_judge else 0))

    def _limit_hit() -> bool:
        """If the subscription limit was hit, log a clear resume message and signal an early stop —
        no point trying the remaining agents (they'd all fail). Smart-cache resumes on re-run."""
        if not any(r.usage_limited for r in result.results):
            return False
        done = [r.agent_type for r in result.results if r.success and r.agent_type != "validation"]
        logger.warning(
            "[orchestrator] %s: subscription usage limit hit after %d/%d agents (%s). Re-run to "
            "resume — smart-cache finishes the rest (~0 extra cost).",
            ticker, len(done), total_llm, ",".join(done) or "none",
        )
        return True

    # Forecast first (4.2): the valuation agent's context includes our model's numbers.
    if run_forecast:
        agent_result = await _run_forecast(ticker, mode)
        result.results.append(agent_result)
        status = "cached" if agent_result.cached else ("ok" if agent_result.success else "FAILED")
        logger.info("[forecast] %s → %s", ticker, status)
        if _limit_hit():
            return result

    for agent_type in analytical:
        agent_result = await _run_single_agent(agent_type, ticker, mode)
        result.results.append(agent_result)
        status = "cached" if agent_result.cached else ("ok" if agent_result.success else "FAILED")
        logger.info("[%s] %s → %s", agent_type, ticker, status)
        if _limit_hit():
            return result

    if run_debate:
        for agent_result in await _run_debate(ticker, mode):
            result.results.append(agent_result)
            status = "cached" if agent_result.cached else ("ok" if agent_result.success else "FAILED")
            logger.info("[%s] %s → %s", agent_result.agent_type, ticker, status)
        if _limit_hit():
            return result

    if run_judge:
        agent_result = await _run_single_agent("judge", ticker, mode)
        result.results.append(agent_result)
        status = "cached" if agent_result.cached else ("ok" if agent_result.success else "FAILED")
        logger.info("[judge] %s → %s", ticker, status)
        if _limit_hit():
            return result

    # Run validation last — always force: it's deterministic (no LLM), so it's free to re-verify
    # the (possibly cached) reports against the freshly-ingested data every run.
    if run_validation:
        agent_result = await _run_single_agent("validation", ticker, mode="force")
        result.results.append(agent_result)
        logger.info("[validation] %s → %s", ticker, "ok" if agent_result.success else "FAILED")

    return result
