"""Analyst consensus estimates from yfinance (free; replaces the unused FMP path).

Consensus is treated as a LOW-WEIGHT divergence check, not a target: it lags reality
(badly for cyclicals) and can sit un-revised for months. We therefore also record how
recently analysts revised (`revisions_30d`) and when we fetched it (`as_of`), so the
agents and scoring can discount or ignore stale consensus. See ANALYST_ROADMAP.md 0.4.
"""

import asyncio
import calendar
import logging
from datetime import date

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.estimate import AnalystEstimate, ConsensusSnapshot
from app.models.financial import Financial

logger = logging.getLogger(__name__)

# yfinance relative period -> approximate months past the latest filed quarter-end.
# Dates are intentionally approximate (we low-weight this data); they only need to be
# future and monotonic for the agent's "upcoming periods" query.
_PERIOD_OFFSETS = {"0q": 3, "+1q": 6, "0y": 12, "+1y": 24}


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _num(v):
    try:
        f = float(v)
        return None if f != f else f  # drop NaN
    except (TypeError, ValueError):
        return None


def _fetch(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    out = {}
    for name in ("earnings_estimate", "revenue_estimate", "eps_revisions"):
        try:
            out[name] = getattr(t, name)
        except Exception:
            out[name] = None
    return out


async def ingest_estimates_yf(db: AsyncSession, ticker: str) -> int:
    """Pull forward EPS/revenue consensus + revision activity from yfinance. Returns rows."""
    latest_end = (await db.execute(
        select(Financial.period_end_date).where(Financial.ticker == ticker)
        .order_by(Financial.period_end_date.desc()).limit(1)
    )).scalar_one_or_none() or date.today()

    data = await asyncio.to_thread(_fetch, ticker)
    eps_df, rev_df, revis_df = data["earnings_estimate"], data["revenue_estimate"], data["eps_revisions"]
    if eps_df is None or eps_df.empty:
        logger.info("[estimates_yf] no consensus for %s", ticker)
        return 0

    today = date.today()
    rows = []
    for period, off in _PERIOD_OFFSETS.items():
        if period not in eps_df.index:
            continue

        def cell(df, col):
            try:
                return _num(df.loc[period, col]) if df is not None and period in df.index else None
            except (KeyError, TypeError):
                return None

        revis = None
        if revis_df is not None and period in revis_df.index:
            up = cell(revis_df, "upLast30days") or 0
            down = cell(revis_df, "downLast30days") or 0
            revis = int(up + down)

        rows.append({
            "ticker": ticker,
            "period_end_date": _add_months(latest_end, off),
            "eps_consensus": cell(eps_df, "avg"),
            "eps_high": cell(eps_df, "high"),
            "eps_low": cell(eps_df, "low"),
            "revenue_consensus": cell(rev_df, "avg"),
            "revenue_high": cell(rev_df, "high"),
            "revenue_low": cell(rev_df, "low"),
            "number_of_analysts": int(cell(eps_df, "numberOfAnalysts") or 0) or None,
            "source": "yfinance",
            "as_of": today,
            "revisions_30d": revis,
        })

    if not rows:
        return 0

    stmt = insert(AnalystEstimate).values(rows)
    cols = ("eps_consensus", "eps_high", "eps_low", "revenue_consensus", "revenue_high",
            "revenue_low", "number_of_analysts", "source", "as_of", "revisions_30d")
    stmt = stmt.on_conflict_do_update(
        constraint="uq_est_ticker_period",
        set_={c: getattr(stmt.excluded, c) for c in cols},
    )
    await db.execute(stmt)

    # 4.1: APPEND a consensus snapshot per fetch — the upsert above keeps only the CURRENT view;
    # this preserves the revisions time-series (one row per ticker/day/period, idempotent within
    # a day). It's the raw material for revisions-momentum + the point-in-time panel.
    snap = insert(ConsensusSnapshot).values([
        {
            "ticker": r["ticker"],
            "as_of": r["as_of"],
            "period_end_date": r["period_end_date"],
            "eps_consensus": r["eps_consensus"],
            "revenue_consensus": r["revenue_consensus"],
            "num_analysts": r["number_of_analysts"],
        }
        for r in rows
    ]).on_conflict_do_nothing(constraint="uq_consensus_snap")
    await db.execute(snap)

    await db.commit()
    logger.info("[estimates_yf] upserted %d consensus periods for %s (+snapshots)", len(rows), ticker)
    return len(rows)
