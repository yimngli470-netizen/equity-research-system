"""Exercise per-ticker IR scraper configs and save any newly-found transcripts.

For every active ticker in `stocks`, calls `fetch_transcript_from_ir` against the
latest quarter that should plausibly be posted on the IR site today, prints the
discovery result (URL / source_kind / length / has_qa), and — if the (ticker,
year, quarter) row is missing from `earnings_transcripts` — runs the same
split/summarize/store path the ingestion orchestrator uses.

Run inside the backend container:
    docker compose exec backend python -m app.scripts.verify_ir_configs
"""

import asyncio
import logging
from datetime import date

from sqlalchemy import select

from app.database import async_session
from app.ingestion.ir.fetcher import fetch_transcript_from_ir
from app.ingestion.transcripts import _store
from app.models.financial import Financial
from app.models.stock import Stock
from app.models.transcript import EarningsTranscript

# Quiet the engine echo so the per-ticker output is readable.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Latest (year, quarter) we expect to find on each ticker's IR site as of today.
# Fiscal-year tickers (AVGO, INTU, MRVL, MU, NVDA) use their fiscal numbering;
# calendar-year tickers use calendar quarters.
TEST_QUARTERS: dict[str, tuple[int, int]] = {
    "AMD":   (2026, 1),
    "AMZN":  (2026, 1),
    "AVGO":  (2026, 1),   # Q1 FY26 ended early Feb 2026
    "GOOGL": (2026, 1),
    "INTU":  (2026, 3),   # Q3 FY26
    "META":  (2026, 1),
    "MRVL":  (2026, 4),   # Q4 FY26
    "MU":    (2026, 2),   # Q2 FY26
    "NVDA":  (2027, 1),   # Q1 FY27
    "TSLA":  (2026, 1),
    "UBER":  (2026, 1),
}


async def _active_tickers() -> list[str]:
    async with async_session() as db:
        result = await db.execute(
            select(Stock.ticker).where(Stock.active.is_(True)).order_by(Stock.ticker)
        )
        return [t for (t,) in result.all()]


async def _existing_row(ticker: str, year: int, quarter: int) -> int | None:
    async with async_session() as db:
        result = await db.execute(
            select(EarningsTranscript.id).where(
                EarningsTranscript.ticker == ticker,
                EarningsTranscript.year == year,
                EarningsTranscript.quarter == quarter,
            )
        )
        return result.scalar_one_or_none()


async def _existing_source(ticker: str, year: int, quarter: int) -> str | None:
    async with async_session() as db:
        result = await db.execute(
            select(EarningsTranscript.source).where(
                EarningsTranscript.ticker == ticker,
                EarningsTranscript.year == year,
                EarningsTranscript.quarter == quarter,
            )
        )
        return result.scalar_one_or_none()


async def _latest_period_end(ticker: str) -> date | None:
    async with async_session() as db:
        result = await db.execute(
            select(Financial.period_end_date)
            .where(Financial.ticker == ticker)
            .order_by(Financial.period_end_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def main() -> None:
    tickers = await _active_tickers()
    print(f"\n=== Verifying IR configs for {len(tickers)} active tickers ===\n")

    saved = 0
    failed: list[tuple[str, str]] = []

    for ticker in tickers:
        if ticker not in TEST_QUARTERS:
            print(f"{ticker}: SKIP — no test quarter configured")
            continue
        year, quarter = TEST_QUARTERS[ticker]
        prefix = f"{ticker} Q{quarter} {year}"
        print(f"\n--- {prefix} ---")

        existing_src = await _existing_source(ticker, year, quarter)
        if existing_src:
            print(f"  already in DB (source={existing_src}) — IR call still useful for verification")

        try:
            result = await fetch_transcript_from_ir(ticker, year, quarter)
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")
            failed.append((ticker, f"exception: {e}"))
            continue

        if not result.success:
            print(f"  FAIL: {result.error}")
            failed.append((ticker, result.error or "unknown"))
            continue

        print(
            f"  OK  source_kind={result.source_kind}  "
            f"len={len(result.content) if result.content else 0}  has_qa={result.has_qa}"
        )
        print(f"  URL: {result.source_url}")

        if existing_src:
            # Don't overwrite an existing row — especially don't clobber an fmp
            # transcript with the IR variant just to test plumbing.
            print("  -> not saving (row already exists)")
            continue

        period_end = await _latest_period_end(ticker)
        if period_end is None:
            print("  -> no financials found, cannot save")
            continue

        fetched = {
            "content": result.content,
            "source": result.source_kind,
            "source_url": result.source_url,
            "has_qa": result.has_qa,
            "transcript_date": None,
        }
        async with async_session() as db:
            await _store(db, ticker, year, quarter, period_end, fetched)
            await db.commit()
        saved += 1
        print("  -> SAVED to earnings_transcripts (summary generated)")

    print("\n=== Summary ===")
    print(f"  saved:  {saved}")
    print(f"  failed: {len(failed)}")
    for ticker, err in failed:
        print(f"    - {ticker}: {err}")


if __name__ == "__main__":
    asyncio.run(main())
