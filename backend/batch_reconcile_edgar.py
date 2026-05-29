"""Validate the EDGAR tag map generalizes across the watchlist (read-only).
Prints a compact per-ticker reconciliation summary + any DIFF/missing details."""

import asyncio

from sqlalchemy import select

from app.database import async_session
from app.ingestion.edgar import extract_quarters
from app.models.financial import Financial
from app.models.stock import Stock

FIELDS = [("revenue", "revenue", False), ("gross_profit", "gross_profit", False),
          ("operating_income", "operating_income", False), ("net_income", "net_income", False),
          ("eps", "eps", True), ("free_cash_flow", "free_cash_flow", False)]


def cmp(e, d, eps=False):
    if e is None or d is None:
        return "miss"
    tol = 0.03 if eps else max(abs(d) * 0.01, 5e6)
    return "ok" if abs(e - d) <= tol else "DIFF"


async def main():
    async with async_session() as db:
        tickers = [t for t in (await db.execute(
            select(Stock.ticker).order_by(Stock.ticker))).scalars().all()]
        fin = {}
        for t in tickers:
            fin[t] = (await db.execute(
                select(Financial).where(Financial.ticker == t))).scalars().all()

    print(f"{'ticker':<8}{'edgar_qtrs':<11}{'span':<22}{'ok':>4}{'diff':>6}{'miss':>6}  notes")
    print("-" * 78)
    for t in tickers:
        rows = fin[t]
        if not rows:
            continue
        try:
            q = extract_quarters(t)
        except Exception as ex:
            print(f"{t:<8}EXTRACT ERROR: {type(ex).__name__}: {ex}")
            continue
        span = f"{q[-1].label}->{q[0].label}" if q else "(none)"
        stats = {"ok": 0, "DIFF": 0, "miss": 0}
        diffs = []
        for r in rows:
            if not q:
                break
            eq = min(q, key=lambda x: abs((x.period_end_date - r.period_end_date).days))
            if abs((eq.period_end_date - r.period_end_date).days) > 7:
                continue
            for attr, dbattr, is_eps in FIELDS:
                ev, dv = getattr(eq, attr), getattr(r, dbattr)
                c = cmp(ev, dv, is_eps)
                stats[c] += 1
                if c == "DIFF":
                    diffs.append(f"{eq.label}/{attr} E={ev:.3g} D={dv:.3g}"
                                 + (" [derived]" if attr in eq.derived else ""))
        note = "; ".join(diffs[:3]) if diffs else "clean"
        print(f"{t:<8}{len(q):<11}{span:<22}{stats['ok']:>4}{stats['DIFF']:>6}{stats['miss']:>6}  {note}")


if __name__ == "__main__":
    asyncio.run(main())
