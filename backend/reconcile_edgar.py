"""Proof: reconcile EDGAR-extracted financials against the existing DB rows (roadmap 0.1).
Read-only — does not write anything. Usage: python /app/reconcile_edgar.py MU"""

import asyncio
import sys

from sqlalchemy import select

from app.database import async_session
from app.ingestion.edgar import extract_quarters
from app.models.financial import Financial

TICKER = sys.argv[1] if len(sys.argv) > 1 else "MU"


def fmt(v, eps=False):
    if v is None:
        return "  —"
    return f"{v:+.2f}" if eps else f"{v/1e9:7.2f}B"


def cmp(edgar, db, eps=False):
    if edgar is None or db is None:
        return "?"
    tol = 0.03 if eps else max(abs(db) * 0.01, 5e6)  # 1% or $5M; 3c for EPS
    return "OK" if abs(edgar - db) <= tol else "DIFF"


async def main():
    q = extract_quarters(TICKER)
    print(f"\nEDGAR extracted {len(q)} quarters for {TICKER}; "
          f"span {q[-1].label} -> {q[0].label}\n")

    async with async_session() as db:
        rows = (await db.execute(
            select(Financial).where(Financial.ticker == TICKER)
            .order_by(Financial.period_end_date.desc())
        )).scalars().all()
    # yfinance period-ends differ from EDGAR's actual fiscal close by a few days,
    # so match each DB row to the nearest EDGAR quarter within 7 days.
    def nearest(dbrow):
        best = min(q, key=lambda eq: abs((eq.period_end_date - dbrow.period_end_date).days))
        return best if abs((best.period_end_date - dbrow.period_end_date).days) <= 7 else None

    print(f"Reconciling {len(rows)} DB quarters against EDGAR "
          f"(nearest end within 7d; tol=1%/$5M, EPS 3c):\n")
    hdr = f"{'period':<10}{'end':<12}{'metric':<14}{'EDGAR':>10}{'DB':>10}  flag"
    print(hdr); print("-" * len(hdr))

    fields = [("revenue", "revenue", False), ("gross_profit", "gross_profit", False),
              ("operating_income", "operating_income", False), ("net_income", "net_income", False),
              ("eps", "eps", True), ("free_cash_flow", "free_cash_flow", False)]
    stats = {"OK": 0, "DIFF": 0, "?": 0}

    for db_row in rows:
        eq = nearest(db_row)
        if eq is None:
            continue  # EDGAR has more history than the DB; only reconcile overlap
        for attr, dbattr, is_eps in fields:
            ev, dv = getattr(eq, attr), getattr(db_row, dbattr)
            flag = cmp(ev, dv, is_eps)
            stats[flag] = stats.get(flag, 0) + 1
            mark = {"OK": "✓", "DIFF": "✗ DIFF", "?": "· (missing)"}[flag]
            d = " [derived]" if attr in eq.derived else ""
            print(f"{eq.label:<10}{str(eq.period_end_date):<12}{attr:<14}"
                  f"{fmt(ev, is_eps):>10}{fmt(dv, is_eps):>10}  {mark}{d}")
        print()

    print(f"SUMMARY: {stats.get('OK',0)} OK · {stats.get('DIFF',0)} DIFF · "
          f"{stats.get('?',0)} missing")
    print(f"EDGAR history depth: {len(q)} quarters vs {len(rows)} in DB "
          f"(+{len(q)-len(rows)} quarters available)")


if __name__ == "__main__":
    asyncio.run(main())
