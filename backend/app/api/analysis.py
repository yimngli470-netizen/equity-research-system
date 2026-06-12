from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.orchestrator import AGENTS, run_all_agents
from app.ingestion.pipeline import ingest_ticker

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class AnalysisRequest(BaseModel):
    ticker: str
    agent_types: list[str] | None = None  # None = all agents
    force: bool = False  # legacy: True ⇒ mode "force" (ignored when mode is set)
    # "smart": re-run an agent only when its INPUTS changed (new filing/transcript/estimates/
    # material news) — a quiet-day run costs ~0 LLM. "force": always re-run. "cache": time-based.
    mode: str | None = None
    ingest_first: bool = True  # refresh market/fundamental/news data before agents


class IngestionRunResponse(BaseModel):
    ticker: str
    prices: int
    financials: int
    valuation: bool
    news: int
    transcripts: int = 0
    earnings_surprises: int = 0
    analyst_estimates: int = 0
    errors: list[str]


class AgentResultResponse(BaseModel):
    agent_type: str
    success: bool
    report: dict | None = None
    error: str | None = None
    cached: bool = False


class AnalysisRunResponse(BaseModel):
    ticker: str
    ingestion: IngestionRunResponse | None = None
    results: list[AgentResultResponse]
    all_succeeded: bool


@router.post("/run", response_model=AnalysisRunResponse)
async def run_analysis(request: AnalysisRequest):
    """Run AI research agents for a ticker.

    Pass specific agent_types or leave empty to run all.
    Set force=true to skip cache and re-run.
    By default, refreshes the ticker's data before running agents.
    """
    ticker = request.ticker.upper()
    ingestion = None
    if request.ingest_first:
        r = await ingest_ticker(ticker)
        ingestion = IngestionRunResponse(
            ticker=r.ticker,
            prices=r.prices,
            financials=r.financials,
            valuation=r.valuation,
            news=r.news,
            transcripts=r.transcripts,
            earnings_surprises=r.earnings_surprises,
            analyst_estimates=r.analyst_estimates,
            errors=r.errors,
        )

    result = await run_all_agents(
        ticker=ticker,
        agent_types=request.agent_types,
        force=request.force,
        mode=request.mode,
    )
    return AnalysisRunResponse(
        ticker=result.ticker,
        ingestion=ingestion,
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
