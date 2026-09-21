from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from app.ingestion.pipeline import run_full_ingestion

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


class IngestionResultResponse(BaseModel):
    ticker: str
    prices: int
    financials: int
    valuation: bool
    news: int
    transcripts: int = 0
    earnings_surprises: int = 0
    analyst_estimates: int = 0
    errors: list[str]
    warnings: list[str] = []


class IngestionRequest(BaseModel):
    tickers: list[str] | None = None  # None = all active stocks
    # None = auto (recompute only on a full-universe run). The peer grid is O(n²) and costs
    # minutes at current universe size, so single-ticker runs skip it; set True to force.
    recompute_peers: bool | None = None


@router.post("/run", response_model=list[IngestionResultResponse])
async def trigger_ingestion(request: IngestionRequest | None = None):
    """Manually trigger the ingestion pipeline.

    Pass specific tickers or leave empty to ingest all active stocks.
    """
    tickers = request.tickers if request else None
    results = await run_full_ingestion(
        tickers,
        recompute_peers=request.recompute_peers if request else None,
    )
    return [
        IngestionResultResponse(
            ticker=r.ticker,
            prices=r.prices,
            financials=r.financials,
            valuation=r.valuation,
            news=r.news,
            transcripts=r.transcripts,
            earnings_surprises=r.earnings_surprises,
            analyst_estimates=r.analyst_estimates,
            errors=r.errors,
            warnings=r.warnings,
        )
        for r in results
    ]

@router.post("/daily-refresh")
async def daily_refresh(background: BackgroundTasks):
    """Run the LLM-free daily data refresh now, in the background.

    Same code path the scheduler fires (ingestion/daily_job.py) — exposed so you can force a
    refresh without waiting for the next trigger. Costs zero LLM tokens; runs no agents.
    """
    from app.ingestion.daily_job import run_daily_data_refresh

    background.add_task(run_daily_data_refresh)
    return {"status": "started", "note": "data-only refresh running in the background (no LLM calls)"}


@router.get("/daily-refresh/status")
async def daily_refresh_status():
    """Result of the most recent daily data refresh, or null if none has run this process."""
    from app.ingestion.daily_job import get_last_run

    return get_last_run()
