from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stock import Stock
from app.models.price import DailyPrice
from app.models.score import StockScore
from app.models.analysis import AnalysisReport
from app.schemas.stock import (
    AnalysisReportResponse,
    DailyPriceResponse,
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
    existing = await db.get(Stock, stock_in.ticker.upper())
    if existing:
        raise HTTPException(status_code=409, detail=f"Stock {stock_in.ticker} already exists")

    stock = Stock(
        ticker=stock_in.ticker.upper(),
        name=stock_in.name,
        sector=stock_in.sector,
        industry=stock_in.industry,
    )
    db.add(stock)
    await db.commit()
    await db.refresh(stock)
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
