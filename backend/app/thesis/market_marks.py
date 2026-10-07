"""Separate, append-only legacy price-return diagnostics. Never fundamental grades.

These are changes in stored close prices, not executed trades or total returns.
They exclude fees/dividends and cannot establish split-adjusted performance when
the old thesis quote has no price-basis provenance. Keep that limitation visible.
"""
import math
from datetime import date

from sqlalchemy import select

from app.accountability.store import save_evidence
from app.models.accountability import ResearchEvidence
from app.models.price import DailyPrice
from app.models.thesis import StockThesis

LEGACY_GRADING_NOTICE = (
    "Legacy EPS and fundamental-thesis grading is frozen under accountability-v2; "
    "saved grades are historical diagnostics. New grades require registered events. "
    "Market-return marks update separately and are not evidence of fundamental forecast accuracy."
)
MARK_NOTE = (
    "Legacy close-price change versus SPY, not trade P&L or total return; no fees/dividends. "
    "Historical quote adjustment basis is unverified. Thesis revisions are correlated observations."
)


async def mark_thesis_returns(db, ticker: str) -> int:
    """Append marks for the newest common stock/SPY session; preserve every old outcome."""
    ticker = ticker.upper()
    theses = (await db.execute(select(StockThesis).where(StockThesis.ticker == ticker))).scalars().all()
    if not theses:
        return 0
    prices = (await db.execute(select(DailyPrice).where(
        DailyPrice.ticker.in_([ticker, "SPY"]), DailyPrice.date <= date.today()))).scalars().all()
    valid = [p for p in prices if p.close is not None and math.isfinite(p.close) and p.close > 0]
    stock = {p.date: p for p in valid if p.ticker == ticker}
    spy = {p.date: p for p in valid if p.ticker == "SPY"}
    common = stock.keys() & spy.keys()
    if not common:
        return 0
    end = max(common)
    written = 0
    for th in theses:
        if th.price_at is None or not math.isfinite(th.price_at) or th.price_at <= 0:
            continue
        source = await db.get(ResearchEvidence, th.evidence_id) if th.evidence_id else None
        recorded_date = (source.payload.get("inputs", {}).get("price_date") if source else None)
        baseline = date.fromisoformat(recorded_date) if recorded_date else th.as_of
        if end <= baseline or end < th.as_of:
            continue
        spy_dates = [d for d in spy if d <= baseline]
        if not spy_dates:
            continue
        spy_start = max(spy_dates)
        stock_return = stock[end].close / th.price_at - 1
        spy_return = spy[end].close / spy[spy_start].close - 1
        payload = {"kind": "legacy_thesis_market_mark", "version": "price-diagnostic-v1",
            "ticker": ticker, "thesis_id": th.id, "mark_date": end.isoformat(),
            "price_at_thesis": th.price_at, "stock_baseline_date": recorded_date,
            "benchmark_baseline_date": spy_start.isoformat(),
            "baseline_rule": "recorded quote date" if recorded_date else "quote date unknown; SPY on/before thesis date",
            "stock_close": stock[end].close, "spy_close": spy[end].close,
            "spy_baseline_close": spy[spy_start].close,
            "realized_return": stock_return, "benchmark_return": spy_return,
            "excess_return": stock_return - spy_return, "note": MARK_NOTE}
        from app.accountability.contracts import digest
        existed = await db.get(ResearchEvidence, digest(payload))
        await save_evidence(db, payload)
        written += existed is None
    return written


async def latest_market_marks(db, ticker: str | None = None) -> dict:
    query = select(ResearchEvidence).where(ResearchEvidence.payload["kind"].astext == "legacy_thesis_market_mark")
    if ticker:
        query = query.where(ResearchEvidence.payload["ticker"].astext == ticker)
    rows = (await db.execute(query.order_by(ResearchEvidence.created_at, ResearchEvidence.id))).scalars().all()
    marks = {}
    for row in rows:
        tid, mark = row.payload["thesis_id"], {**row.payload, "evidence_id": row.id}
        if tid not in marks or marks[tid]["mark_date"] <= mark["mark_date"]:
            marks[tid] = mark
    return marks
