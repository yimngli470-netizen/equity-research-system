"""Fetch quarterly financials and point-in-time valuation metrics from yfinance."""

import logging
import math
from datetime import date

import yfinance as yf
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import Financial
from app.models.valuation import Valuation

logger = logging.getLogger(__name__)


def _safe(value) -> float | None:
    """Convert a value to float, returning None for NaN/None."""
    if value is None:
        return None
    try:
        f = float(value)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _get(df, label, col):
    """Safely get a value from a DataFrame by row label and column."""
    try:
        if label in df.index:
            return _safe(df.loc[label, col])
    except (KeyError, TypeError):
        pass
    return None


async def ingest_financials(db: AsyncSession, ticker: str) -> int:
    """Fetch quarterly income statement, cash flow, and balance sheet.

    Returns number of quarterly records upserted.
    """
    logger.info("Fetching quarterly financials for %s", ticker)

    stock = yf.Ticker(ticker)

    income = stock.quarterly_income_stmt
    cashflow = stock.quarterly_cashflow
    balance = stock.quarterly_balance_sheet

    if income.empty:
        logger.warning("No income statement data for %s", ticker)
        return 0

    rows = []
    for col in income.columns:
        period_end = col.date() if hasattr(col, "date") else col

        rows.append(
            {
                "ticker": ticker,
                "period": _quarter_label(period_end),
                "period_end_date": period_end,
                # Income statement
                "revenue": _get(income, "Total Revenue", col),
                "gross_profit": _get(income, "Gross Profit", col),
                "operating_income": _get(income, "Operating Income", col),
                "net_income": _get(income, "Net Income", col),
                "eps": _get(income, "Diluted EPS", col),
                # Cash flow
                "free_cash_flow": _get(cashflow, "Free Cash Flow", col) if not cashflow.empty else None,
                "operating_cash_flow": _get(cashflow, "Operating Cash Flow", col) if not cashflow.empty else None,
                # Balance sheet
                "total_debt": _get(balance, "Total Debt", col) if not balance.empty else None,
                "cash_and_equivalents": _get(balance, "Cash And Cash Equivalents", col) if not balance.empty else None,
                "total_assets": _get(balance, "Total Assets", col) if not balance.empty else None,
                "total_equity": _get(balance, "Stockholders Equity", col) if not balance.empty else None,
                "shares_outstanding": _get(balance, "Share Issued", col) if not balance.empty else None,
            }
        )

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

    logger.info("Upserted %d quarterly financial records for %s", len(rows), ticker)
    return len(rows)


async def ingest_valuation(db: AsyncSession, ticker: str) -> bool:
    """Capture a point-in-time valuation snapshot from yfinance .info.

    Returns True if a row was upserted, False otherwise.
    """
    logger.info("Fetching valuation metrics for %s", ticker)

    stock = yf.Ticker(ticker)
    info = stock.info

    if not info:
        logger.warning("No info data for %s", ticker)
        return False

    row = {
        "ticker": ticker,
        "date": date.today(),
        # Multiples
        "forward_pe": _safe(info.get("forwardPE")),
        "trailing_pe": _safe(info.get("trailingPE")),
        "peg_ratio": _safe(info.get("pegRatio")),
        "price_to_sales": _safe(info.get("priceToSalesTrailing12Months")),
        "price_to_book": _safe(info.get("priceToBook")),
        "ev_to_revenue": _safe(info.get("enterpriseToRevenue")),
        "ev_to_ebitda": _safe(info.get("enterpriseToEbitda")),
        # Per-share
        "trailing_eps": _safe(info.get("trailingEps")),
        "forward_eps": _safe(info.get("forwardEps")),
        # Growth
        "earnings_growth": _safe(info.get("earningsGrowth")),
        "revenue_growth": _safe(info.get("revenueGrowth")),
        # Margins
        "gross_margins": _safe(info.get("grossMargins")),
        "operating_margins": _safe(info.get("operatingMargins")),
        "profit_margins": _safe(info.get("profitMargins")),
        # Size
        "market_cap": _safe(info.get("marketCap")),
        "enterprise_value": _safe(info.get("enterpriseValue")),
        "shares_outstanding": _safe(info.get("sharesOutstanding")),
    }

    stmt = insert(Valuation).values([row])
    stmt = stmt.on_conflict_do_update(
        constraint="uq_val_ticker_date",
        set_={k: getattr(stmt.excluded, k) for k in row if k not in ("ticker", "date")},
    )
    await db.execute(stmt)
    await db.commit()

    logger.info("Upserted valuation snapshot for %s on %s", ticker, date.today())
    return True


def _quarter_label(d: date) -> str:
    """Convert a date to a fiscal quarter label like 'Q1 2026'."""
    q = (d.month - 1) // 3 + 1
    return f"Q{q} {d.year}"
