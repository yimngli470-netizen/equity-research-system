"""Kill-signals API — the standing per-ticker list of what would break the thesis.

CRUD over `ticker_kill_signals`. The judge feeds candidates in automatically (see
kill_signals/service.sync_judge_candidates, called at the end of the decision run); everything
here is the user curating that list.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.kill_signals import service
from app.models.stock import Stock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kill-signals", tags=["kill-signals"])


class KillSignalCreate(BaseModel):
    signal: str = Field(min_length=3, max_length=2000)
    rationale: str | None = None
    severity: str = "high"


class KillSignalUpdate(BaseModel):
    signal: str | None = None
    rationale: str | None = None
    severity: str | None = None
    status: str | None = None       # candidate | active | tripped | dismissed
    by_date: str | None = None
    tripped_note: str | None = None


@router.get("/{ticker}")
async def get_kill_signals(
    ticker: str, include_dismissed: bool = False, db: AsyncSession = Depends(get_db)
):
    """Standing signals + pending judge candidates for one ticker.

    Split by status so the UI can render the review queue separately from the live list.
    """
    ticker = ticker.upper()
    if await db.get(Stock, ticker) is None:
        raise HTTPException(404, f"Stock {ticker} not found")

    rows = await service.list_signals(db, ticker, include_dismissed=include_dismissed)
    return {
        "ticker": ticker,
        "active": [r for r in rows if r["status"] == "active"],
        "tripped": [r for r in rows if r["status"] == "tripped"],
        "candidates": [r for r in rows if r["status"] == "candidate"],
        "dismissed": [r for r in rows if r["status"] == "dismissed"],
    }


@router.post("/{ticker}", status_code=201)
async def add_kill_signal(
    ticker: str, payload: KillSignalCreate, db: AsyncSession = Depends(get_db)
):
    ticker = ticker.upper()
    if await db.get(Stock, ticker) is None:
        raise HTTPException(404, f"Stock {ticker} not found")

    created = await service.create_signal(
        db, ticker, payload.signal,
        rationale=payload.rationale, severity=payload.severity,
        status="active", source="manual",
    )
    if created is None:
        # Unique (ticker, signal) — could be an active duplicate or a dismissed row the user is
        # re-adding. Say which, so the UI can offer "re-activate" instead of silently failing.
        existing = await service.list_signals(db, ticker, include_dismissed=True)
        match = next((r for r in existing if r["signal"] == payload.signal.strip()), None)
        raise HTTPException(
            409,
            f"{ticker} already has this signal"
            + (f" (status: {match['status']}, id {match['id']})" if match else ""),
        )
    return created


@router.patch("/id/{signal_id}")
async def patch_kill_signal(
    signal_id: int, payload: KillSignalUpdate, db: AsyncSession = Depends(get_db)
):
    """Edit a signal, or move it between statuses (accept / dismiss / trip)."""
    updated = await service.update_signal(
        db, signal_id, **payload.model_dump(exclude_unset=True)
    )
    if updated is None:
        raise HTTPException(404, f"Kill signal {signal_id} not found")
    return updated


@router.delete("/id/{signal_id}", status_code=204)
async def remove_kill_signal(signal_id: int, db: AsyncSession = Depends(get_db)):
    """Hard-delete. To reject a JUDGE proposal use PATCH status='dismissed' instead — a deleted
    candidate is re-offered by the next judge run, a dismissed one is not."""
    if not await service.delete_signal(db, signal_id):
        raise HTTPException(404, f"Kill signal {signal_id} not found")


@router.post("/{ticker}/generate")
async def generate(ticker: str, force: bool = False, db: AsyncSession = Depends(get_db)):
    """LLM-seed the list (one Sonnet call). No-op when the ticker already has signals unless
    force=true — in which case new proposals are ADDED alongside the existing ones, never
    replacing what you curated."""
    ticker = ticker.upper()
    stock = await db.get(Stock, ticker)
    if stock is None:
        raise HTTPException(404, f"Stock {ticker} not found")

    from app.ingestion.bootstrap import _company_info

    info = await asyncio.to_thread(_company_info, ticker, stock)
    status, count = await service.generate_kill_signals(db, ticker, info, force=force)
    return {"ticker": ticker, "status": status, "added": count}


@router.post("/{ticker}/sync-judge")
async def sync_judge(ticker: str, db: AsyncSession = Depends(get_db)):
    """Pull the latest judge run's kill_criteria in as candidates. Runs automatically after each
    decision; exposed here for backfilling tickers whose judge ran before this feature existed."""
    ticker = ticker.upper()
    if await db.get(Stock, ticker) is None:
        raise HTTPException(404, f"Stock {ticker} not found")
    added = await service.sync_judge_candidates(db, ticker)
    return {"ticker": ticker, "candidates_added": added}


@router.post("/{ticker}/evaluate")
async def evaluate(ticker: str, force: bool = False, db: AsyncSession = Depends(get_db)):
    """Evaluate active signals against the latest reported quarter (one Sonnet call).

    Runs automatically inside the pipeline's ingest step; exposed here to re-check on demand.
    Idempotent per (signal, quarter) unless force=true. A `tripped` verdict flips the signal.
    """
    ticker = ticker.upper()
    if await db.get(Stock, ticker) is None:
        raise HTTPException(404, f"Stock {ticker} not found")

    from app.kill_signals import evaluate_kill_signals

    n = await evaluate_kill_signals(db, ticker, force=force)
    return {"ticker": ticker, "evaluated": n}


@router.get("/{ticker}/evaluations")
async def evaluation_history(ticker: str, db: AsyncSession = Depends(get_db)):
    """Full per-quarter verdict history — the audit trail behind each signal's status."""
    from sqlalchemy import select

    from app.models.kill_signal import KillSignalEvaluation

    rows = (
        await db.execute(
            select(KillSignalEvaluation)
            .where(KillSignalEvaluation.ticker == ticker.upper())
            .order_by(KillSignalEvaluation.period_end_date.desc(), KillSignalEvaluation.signal_id)
        )
    ).scalars().all()
    return [
        {
            "signal_id": r.signal_id,
            "period_end_date": r.period_end_date.isoformat() if r.period_end_date else None,
            "verdict": r.verdict,
            "evidence_quote": r.evidence_quote,
            "reasoning": r.reasoning,
            "source": r.source,
            "source_url": r.source_url,
        }
        for r in rows
    ]
