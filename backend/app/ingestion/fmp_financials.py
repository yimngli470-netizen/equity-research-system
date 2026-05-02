"""Fetch quarterly financials from FMP — replaces yfinance when an API key is set.

FMP gives 5+ years of quarterly history and updates within hours of an earnings
release, vs yfinance's ~5-quarter window and Yahoo's update lag.
"""

import logging
import math
from datetime import date, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.fmp_client import get_fmp_client
from app.models.financial import Financial

logger = logging.getLogger(__name__)


def _safe(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _quarter_label(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"Q{q} {d.year}"


async def ingest_financials_fmp(db: AsyncSession, ticker: str, limit: int = 20) -> int:
    """Pull quarterly income / cash flow / balance sheet from FMP and upsert.

    Costs 3 FMP calls per ticker. Returns number of quarters upserted.
    """
    client = get_fmp_client()
    if client is None:
        logger.warning("FMP client unavailable — skipping FMP financials for %s", ticker)
        return 0

    income = await client.get_income_statement(ticker, "quarter", limit)
    cashflow = await client.get_cash_flow_statement(ticker, "quarter", limit)
    balance = await client.get_balance_sheet_statement(ticker, "quarter", limit)

    if not income:
        logger.warning("FMP returned no income statement for %s", ticker)
        return 0

    # Index cashflow + balance by date for join
    cf_by_date = {row.get("date"): row for row in cashflow if row.get("date")}
    bs_by_date = {row.get("date"): row for row in balance if row.get("date")}

    rows = []
    for inc in income:
        period_end = _parse_date(inc.get("date"))
        if not period_end:
            continue

        cf = cf_by_date.get(inc.get("date"), {})
        bs = bs_by_date.get(inc.get("date"), {})

        rows.append({
            "ticker": ticker,
            "period": _quarter_label(period_end),
            "period_end_date": period_end,
            "revenue": _safe(inc.get("revenue")),
            "gross_profit": _safe(inc.get("grossProfit")),
            "operating_income": _safe(inc.get("operatingIncome")),
            "net_income": _safe(inc.get("netIncome")),
            "eps": _safe(inc.get("epsdiluted") or inc.get("eps")),
            "free_cash_flow": _safe(cf.get("freeCashFlow")),
            "operating_cash_flow": _safe(cf.get("operatingCashFlow")),
            "total_debt": _safe(bs.get("totalDebt")),
            "cash_and_equivalents": _safe(bs.get("cashAndCashEquivalents")),
            "total_assets": _safe(bs.get("totalAssets")),
            "total_equity": _safe(bs.get("totalStockholdersEquity")),
            "shares_outstanding": _safe(
                inc.get("weightedAverageShsOutDil") or inc.get("weightedAverageShsOut")
            ),
        })

    if not rows:
        return 0

    stmt = insert(Financial).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_fin_ticker_period",
        set_={
            "period": stmt.excluded.period,
            "revenue": stmt.excluded.revenue,
            "gross_profit": stmt.excluded.gross_profit,
            "operating_income": stmt.excluded.operating_income,
            "net_income": stmt.excluded.net_income,
            "eps": stmt.excluded.eps,
            "free_cash_flow": stmt.excluded.free_cash_flow,
            "operating_cash_flow": stmt.excluded.operating_cash_flow,
            "total_debt": stmt.excluded.total_debt,
            "cash_and_equivalents": stmt.excluded.cash_and_equivalents,
            "total_assets": stmt.excluded.total_assets,
            "total_equity": stmt.excluded.total_equity,
            "shares_outstanding": stmt.excluded.shares_outstanding,
        },
    )
    await db.execute(stmt)
    await db.commit()

    logger.info("FMP: upserted %d quarterly financial records for %s", len(rows), ticker)
    return len(rows)
