"""Fetch daily price history from yfinance and upsert into daily_prices."""

import logging
from datetime import date, timedelta

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price import DailyPrice

logger = logging.getLogger(__name__)


async def ingest_prices(
    db: AsyncSession,
    ticker: str,
    lookback_days: int = 400,
) -> int:
    """Fetch daily prices for a ticker and upsert into the database.

    Args:
        db: Async database session.
        ticker: Stock ticker symbol.
        lookback_days: How many calendar days of history to fetch.
            Default 400 gives ~1 year of trading days plus buffer.

    Returns:
        Number of rows upserted.
    """
    logger.info("Fetching prices for %s (lookback=%d days)", ticker, lookback_days)

    start = date.today() - timedelta(days=lookback_days)
    end = date.today()

    stock = yf.Ticker(ticker)
    df = stock.history(start=start.isoformat(), end=end.isoformat(), auto_adjust=False)

    if df.empty:
        logger.warning("No price data returned for %s", ticker)
        return 0

    rows = []
    for idx, row in df.iterrows():
        trade_date = idx.date() if hasattr(idx, "date") else idx
        rows.append(
            {
                "ticker": ticker,
                "date": trade_date,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "adj_close": float(row["Adj Close"]),
                "volume": int(row["Volume"]),
            }
        )

    # Upsert: insert or update on conflict
    stmt = insert(DailyPrice).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_price_ticker_date",
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "adj_close": stmt.excluded.adj_close,
            "volume": stmt.excluded.volume,
        },
    )
    await db.execute(stmt)
    await db.commit()

    logger.info("Upserted %d price rows for %s", len(rows), ticker)
    return len(rows)
