from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.orchestrator import AGENTS, run_all_agents

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class AnalysisRequest(BaseModel):
    ticker: str
    agent_types: list[str] | None = None  # None = all agents
    force: bool = False  # skip cache


class AgentResultResponse(BaseModel):
    agent_type: str
    success: bool
    report: dict | None = None
    error: str | None = None
    cached: bool = False


class AnalysisRunResponse(BaseModel):
    ticker: str
    results: list[AgentResultResponse]
    all_succeeded: bool


@router.post("/run", response_model=AnalysisRunResponse)
async def run_analysis(request: AnalysisRequest):
    """Run AI research agents for a ticker.

    Pass specific agent_types or leave empty to run all.
    Set force=true to skip cache and re-run.
    """
    result = await run_all_agents(
        ticker=request.ticker.upper(),
        agent_types=request.agent_types,
        force=request.force,
    )
    return AnalysisRunResponse(
        ticker=result.ticker,
        results=[
            AgentResultResponse(
                agent_type=r.agent_type,
                success=r.success,
                report=r.report,
                error=r.error,
                cached=r.cached,
            )
            for r in result.results
        ],
        all_succeeded=result.all_succeeded,
    )


@router.get("/agents")
async def list_agents():
    """List available agent types and their cache settings."""
    return {
        name: {
            "max_age_days": cls().max_age_days,
            "model": cls().model,
        }
        for name, cls in AGENTS.items()
    }
