"""Fetch daily price history from yfinance and upsert into daily_prices."""

import asyncio
import logging
import math
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
    # yfinance treats `end` as exclusive; include tomorrow so today's completed
    # daily bar is eligible when the user refreshes after market close.
    end = date.today() + timedelta(days=1)

    stock = yf.Ticker(ticker)
    df = await asyncio.to_thread(
        stock.history, start=start.isoformat(), end=end.isoformat(), auto_adjust=False
    )

    if df.empty:
        logger.warning("No price data returned for %s", ticker)
        return 0

    rows = []
    skipped = 0
    for idx, row in df.iterrows():
        trade_date = idx.date() if hasattr(idx, "date") else idx
        o, h, lo, c, ac = (float(row[k]) for k in ("Open", "High", "Low", "Close", "Adj Close"))
        # yfinance sometimes returns an incomplete bar (e.g. today's, intraday) with NaN fields.
        # A persisted NaN poisons everything downstream (JSON null → frontend crash, NaN momentum),
        # so skip any row that isn't fully finite — it'll ingest cleanly on the next run.
        if not all(math.isfinite(v) for v in (o, h, lo, c, ac)):
            skipped += 1
            logger.warning("[prices] %s %s: non-finite OHLC from yfinance — row skipped", ticker, trade_date)
            continue
        vol = row["Volume"]
        rows.append(
            {
                "ticker": ticker,
                "date": trade_date,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "adj_close": ac,
                "volume": int(vol) if math.isfinite(float(vol)) else 0,
            }
        )

    if not rows:
        logger.warning("No valid price rows for %s (%d skipped)", ticker, skipped)
        return 0

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


BENCHMARK_TICKER = "SPY"  # plain daily_prices rows; deliberately NOT in the stocks watchlist


async def ingest_benchmark_prices(db: AsyncSession, lookback_days: int = 400) -> int:
    """Keep the SPY benchmark history fresh (roadmap 4.1) so thesis grading can compute
    benchmark-relative (excess) returns. Skips if today's/yesterday's bar is already present —
    at most one yfinance call per day no matter how many tickers run."""
    latest = (
        await db.execute(
            select(DailyPrice.date).where(DailyPrice.ticker == BENCHMARK_TICKER)
            .order_by(DailyPrice.date.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if latest is not None and (date.today() - latest).days < 1:
        return 0
    # First run backfills ~10y so past theses/backtests have benchmark coverage.
    lookback = lookback_days if latest is not None else 3700
    return await ingest_prices(db, BENCHMARK_TICKER, lookback_days=lookback)
