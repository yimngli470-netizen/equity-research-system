"""Portfolio API (roadmap 6.2) — manual CRUD over the book + the computed view.

The book the sizing engine reads (`book_concentration`) and the page renders (`compute_book`) are
the same object. Positions and cash are entered by hand (no brokerage link), consistent with the
free-data, local-first stance.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.portfolio import service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class PositionIn(BaseModel):
    shares: float
    cost_basis: float | None = None
    opened_date: date | None = None
    notes: str | None = None


class CashIn(BaseModel):
    cash: float


@router.get("/book")
async def get_book(correlations: bool = True, db: AsyncSession = Depends(get_db)):
    """The full computed book — weights, sector exposure, P&L, portfolio beta, holding correlations."""
    return (await service.compute_book(db, with_correlations=correlations)).to_dict()


@router.get("/positions")
async def list_positions(db: AsyncSession = Depends(get_db)):
    rows = await service.list_positions(db)
    return [
        {"ticker": p.ticker, "shares": p.shares, "cost_basis": p.cost_basis,
         "opened_date": str(p.opened_date) if p.opened_date else None, "notes": p.notes}
        for p in rows
    ]


@router.put("/positions/{ticker}")
async def upsert_position(ticker: str, body: PositionIn, db: AsyncSession = Depends(get_db)):
    """Add or update a holding (shares<=0 removes it)."""
    p = await service.upsert_position(
        db, ticker, shares=body.shares, cost_basis=body.cost_basis,
        opened_date=body.opened_date, notes=body.notes)
    if p is None:
        return {"ticker": ticker.upper(), "removed": True}
    return {"ticker": p.ticker, "shares": p.shares, "cost_basis": p.cost_basis}


@router.delete("/positions/{ticker}")
async def delete_position(ticker: str, db: AsyncSession = Depends(get_db)):
    removed = await service.delete_position(db, ticker)
    return {"ticker": ticker.upper(), "removed": removed}


@router.get("/cash")
async def get_cash(db: AsyncSession = Depends(get_db)):
    acct = await service.get_account(db)
    return {"cash": acct.cash, "label": acct.label}


@router.put("/cash")
async def set_cash(body: CashIn, db: AsyncSession = Depends(get_db)):
    acct = await service.set_cash(db, body.cash)
    return {"cash": acct.cash}
