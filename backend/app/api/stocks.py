import asyncio
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stock import Stock
from app.models.price import DailyPrice
from app.models.score import StockScore
from app.models.analysis import AnalysisReport
from app.models.financial import Financial
from app.models.valuation import Valuation
from app.schemas.stock import (
    AnalysisReportResponse,
    DailyPriceResponse,
    FinancialResponse,
    ValuationResponse,
    StockCreate,
    StockResponse,
    StockScoreResponse,
    StockWithLatestPrice,
)

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/", response_model=list[StockWithLatestPrice])
async def list_stocks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Stock).where(Stock.active.is_(True)).order_by(Stock.ticker))
    stocks = result.scalars().all()

    enriched = []
    for stock in stocks:
        # Get latest two prices for change calculation
        prices_result = await db.execute(
            select(DailyPrice)
            .where(DailyPrice.ticker == stock.ticker)
            .order_by(DailyPrice.date.desc())
            .limit(2)
        )
        prices = prices_result.scalars().all()

        latest_price = prices[0].close if prices else None
        change_pct = None
        if len(prices) >= 2:
            change_pct = (prices[0].close - prices[1].close) / prices[1].close

        enriched.append(
            StockWithLatestPrice(
                **StockResponse.model_validate(stock).model_dump(),
                latest_price=latest_price,
                price_change_pct=change_pct,
            )
        )

    return enriched


@router.post("/", response_model=StockResponse, status_code=201)
async def add_stock(stock_in: StockCreate, db: AsyncSession = Depends(get_db)):
    ticker = stock_in.ticker.upper()
    existing = await db.get(Stock, ticker)
    if existing and existing.active:
        raise HTTPException(status_code=409, detail=f"Stock {ticker} already exists")

    # Reactivate soft-deleted stock
    if existing and not existing.active:
        existing.active = True
        await db.commit()
        await db.refresh(existing)
        import asyncio
        from app.ingestion.pipeline import ingest_ticker
        asyncio.create_task(ingest_ticker(ticker))
        return existing

    # Auto-resolve name, sector, industry from yfinance if not provided
    name = stock_in.name
    sector = stock_in.sector
    industry = stock_in.industry

    if not sector or not industry or name == ticker:
        try:
            import yfinance as yf
            info = await asyncio.to_thread(lambda: yf.Ticker(ticker).info)
            if info:
                if not sector:
                    sector = info.get("sector")
                if not industry:
                    industry = info.get("industry")
                if name == ticker or not name:
                    name = info.get("longName") or info.get("shortName") or name
        except Exception:
            pass  # proceed with whatever we have

    stock = Stock(
        ticker=ticker,
        name=name,
        sector=sector,
        industry=industry,
    )
    db.add(stock)
    await db.commit()
    await db.refresh(stock)

    # Auto-trigger ingestion in background
    import asyncio
    from app.ingestion.pipeline import ingest_ticker
    asyncio.create_task(ingest_ticker(ticker))

    return stock


@router.get("/{ticker}", response_model=StockResponse)
async def get_stock(ticker: str, db: AsyncSession = Depends(get_db)):
    stock = await db.get(Stock, ticker.upper())
    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {ticker} not found")
    return stock


@router.delete("/{ticker}", status_code=204)
async def remove_stock(ticker: str, db: AsyncSession = Depends(get_db)):
    stock = await db.get(Stock, ticker.upper())
    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {ticker} not found")
    stock.active = False
    await db.commit()


@router.get("/{ticker}/prices", response_model=list[DailyPriceResponse])
async def get_prices(
    ticker: str,
    start: date | None = None,
    end: date | None = None,
    limit: int = 252,
    db: AsyncSession = Depends(get_db),
):
    query = select(DailyPrice).where(DailyPrice.ticker == ticker.upper())
    if start:
        query = query.where(DailyPrice.date >= start)
    if end:
        query = query.where(DailyPrice.date <= end)
    query = query.order_by(DailyPrice.date.desc()).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{ticker}/financials", response_model=list[FinancialResponse])
async def get_financials(ticker: str, limit: int = 8, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Financial)
        .where(Financial.ticker == ticker.upper())
        .order_by(Financial.period_end_date.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{ticker}/valuation", response_model=ValuationResponse | None)
async def get_latest_valuation(ticker: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Valuation)
        .where(Valuation.ticker == ticker.upper())
        .order_by(Valuation.date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/{ticker}/scores", response_model=list[StockScoreResponse])
async def get_scores(ticker: str, limit: int = 30, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StockScore)
        .where(StockScore.ticker == ticker.upper())
        .order_by(StockScore.date.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{ticker}/scores/latest", response_model=StockScoreResponse | None)
async def get_latest_score(ticker: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StockScore)
        .where(StockScore.ticker == ticker.upper())
        .order_by(StockScore.date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/{ticker}/analysis", response_model=list[AnalysisReportResponse])
async def get_analysis_reports(
    ticker: str,
    agent_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(AnalysisReport).where(AnalysisReport.ticker == ticker.upper())
    if agent_type:
        query = query.where(AnalysisReport.agent_type == agent_type)
    query = query.order_by(AnalysisReport.run_date.desc()).limit(10)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{ticker}/transcript-debug")
async def debug_transcript_filters(ticker: str, db: AsyncSession = Depends(get_db)):
    """Inspect what each consumer sees from the latest transcript.

    Shows two distinct views:
    - The LLM-generated structured summary (what earnings/industry/valuation
      agents actually consume — see transcript_summarizer.py)
    - The keyword-filtered raw text (what the validator consumes so it can
      cross-check against source quotes)
    """
    from app.agents.transcript_summarizer import format_summary_for_agent
    from app.agents.transcript_utils import prepare_earnings_context
    from app.models.transcript import EarningsTranscript

    result = await db.execute(
        select(EarningsTranscript)
        .where(EarningsTranscript.ticker == ticker.upper())
        .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
        .limit(1)
    )
    transcript = result.scalar_one_or_none()
    if not transcript:
        raise HTTPException(404, f"No transcript found for {ticker}")

    full_text = transcript.full_text or ""
    prepared = transcript.prepared_remarks or ""
    qa = transcript.qa_section or ""

    summary = transcript.summary
    return {
        "ticker": ticker.upper(),
        "transcript": {
            "year": transcript.year,
            "quarter": transcript.quarter,
            "transcript_date": transcript.transcript_date.isoformat() if transcript.transcript_date else None,
            "full_text_chars": len(full_text),
            "prepared_remarks_chars": len(prepared),
            "qa_section_chars": len(qa),
            "estimated_tokens_full": len(full_text) // 4,
            "has_llm_summary": summary is not None,
        },
        "llm_summary_raw": summary,
        "agent_views": {
            "earnings_agent (LLM summary)": format_summary_for_agent(summary, focus="earnings") if summary else None,
            "industry_agent (LLM summary)": format_summary_for_agent(summary, focus="industry") if summary else None,
            "valuation_agent (LLM summary)": format_summary_for_agent(summary, focus="valuation") if summary else None,
            "validation_agent (keyword-filtered raw)": prepare_earnings_context(prepared, qa, max_tokens=8000),
        },
    }
