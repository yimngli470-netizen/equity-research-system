from fastapi import APIRouter
from pydantic import BaseModel

from app.ingestion.pipeline import run_full_ingestion

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


class IngestionResultResponse(BaseModel):
    ticker: str
    prices: int
    financials: int
    valuation: bool
    news: int
    errors: list[str]


class IngestionRequest(BaseModel):
    tickers: list[str] | None = None  # None = all active stocks


@router.post("/run", response_model=list[IngestionResultResponse])
async def trigger_ingestion(request: IngestionRequest | None = None):
    """Manually trigger the ingestion pipeline.

    Pass specific tickers or leave empty to ingest all active stocks.
    """
    tickers = request.tickers if request else None
    results = await run_full_ingestion(tickers)
    return [
        IngestionResultResponse(
            ticker=r.ticker,
            prices=r.prices,
            financials=r.financials,
            valuation=r.valuation,
            news=r.news,
            errors=r.errors,
        )
        for r in results
    ]
