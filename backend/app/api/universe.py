"""Universe screening API (roadmap 6.1e) — the two-tier idea-generation surface.

Read: a ranked screen across the ~520 S&P 500 + NASDAQ-100 names (tier-1, hard features + rule
archetype), with each name's rank overall and within its archetype. Write: refresh the universe
(batch tier-1 ingest, background) and promote a name to the watchlist (the full LLM pipeline,
background). The pull model is intact — nothing screens or promotes itself; both writes are explicit.

The long jobs run as fire-and-forget asyncio tasks (the codebase's pattern) with a small in-memory
status so the UI can show progress; a batch of 520 names is far too long to block a request.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.score import StockScore
from app.models.stock import Stock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/universe", tags=["universe"])

# In-memory job status (single-process backend; resets on restart — fine for a personal tool).
_refresh_job: dict = {"running": False, "started_at": None, "finished_at": None, "summary": None}
_promotions: dict[str, dict] = {}  # ticker -> {running, steps, finished_at}


# ── Screen ───────────────────────────────────────────────────────────────────────────────────────
class ScreenRow(BaseModel):
    ticker: str
    name: str
    sector: str | None
    archetype: str | None
    archetype_source: str | None          # "rules" (provisional) | "llm" (confirmed)
    coverage_tier: str                    # "universe" | "watchlist"
    composite_score: float
    signal: str
    as_of: str
    rank: int
    total: int
    archetype_rank: int
    archetype_total: int


@router.get("/screen", response_model=list[ScreenRow])
async def screen(
    archetype: str | None = None,
    tier: str | None = None,
    limit: int = 600,
    db: AsyncSession = Depends(get_db),
):
    """Ranked screen across every scored name (universe + watchlist).

    `composite_score` is the peer-relative hard-feature screen (tier-1 names have neutral AI
    categories). Ranks are over the FULL scored set; the `archetype`/`tier` params filter the
    returned rows but not the ranking, so a filtered view still shows true universe standing.
    """
    # Latest score per ticker (window: max date per ticker).
    latest_date = (
        select(StockScore.ticker, func.max(StockScore.date).label("d"))
        .group_by(StockScore.ticker)
        .subquery()
    )
    rows = (
        await db.execute(
            select(Stock, StockScore)
            .join(latest_date, latest_date.c.ticker == Stock.ticker)
            .join(StockScore, (StockScore.ticker == latest_date.c.ticker)
                  & (StockScore.date == latest_date.c.d))
        )
    ).all()

    scored = sorted(
        ({"stock": s, "score": sc} for s, sc in rows),
        key=lambda r: r["score"].composite_score, reverse=True,
    )
    total = len(scored)
    # Archetype ranks (over the full set, in composite-desc order).
    arch_counts: dict[str | None, int] = {}
    for r in scored:
        a = r["stock"].archetype
        arch_counts[a] = arch_counts.get(a, 0) + 1
    arch_seen: dict[str | None, int] = {}

    out: list[ScreenRow] = []
    for i, r in enumerate(scored):
        s, sc = r["stock"], r["score"]
        a = s.archetype
        arch_seen[a] = arch_seen.get(a, 0) + 1
        if archetype and a != archetype:
            continue
        if tier and s.coverage_tier != tier:
            continue
        out.append(ScreenRow(
            ticker=s.ticker, name=s.name, sector=s.sector, archetype=a,
            archetype_source=s.archetype_source, coverage_tier=s.coverage_tier,
            composite_score=round(sc.composite_score, 4), signal=sc.signal, as_of=str(sc.date),
            rank=i + 1, total=total,
            archetype_rank=arch_seen[a], archetype_total=arch_counts[a],
        ))
        if len(out) >= limit:
            break
    return out


# ── Status ───────────────────────────────────────────────────────────────────────────────────────
@router.get("/status")
async def status(db: AsyncSession = Depends(get_db)):
    """Universe coverage counts + the current/last refresh job + any in-flight promotions."""
    total = (await db.execute(select(func.count()).select_from(Stock))).scalar() or 0
    watchlist = (await db.execute(
        select(func.count()).select_from(Stock).where(Stock.coverage_tier == "watchlist"))).scalar() or 0
    universe = (await db.execute(
        select(func.count()).select_from(Stock).where(Stock.coverage_tier == "universe"))).scalar() or 0
    scored = (await db.execute(
        select(func.count(func.distinct(StockScore.ticker))))).scalar() or 0

    snapshot_as_of = None
    try:
        from app.universe.constituents import load_snapshot
        snapshot_as_of = load_snapshot().get("as_of")
    except Exception:
        pass

    return {
        "total_names": total,
        "watchlist": watchlist,
        "universe": universe,
        "scored": scored,
        "constituents_as_of": snapshot_as_of,
        "refresh_job": _refresh_job,
        "promotions": {t: {k: v for k, v in p.items() if k != "steps"} for t, p in _promotions.items()},
    }


# ── Refresh (background) ───────────────────────────────────────────────────────────────────────────
class RefreshRequest(BaseModel):
    refresh_constituents: bool = False    # re-pull index membership from Wikipedia first
    skip_fresh_days: int = 7              # skip names ingested within N days (resumable); 0 = full
    max_names: int | None = None          # cap for a partial/smoke run


async def _run_refresh(req: RefreshRequest) -> None:
    _refresh_job.update(running=True, started_at=datetime.now(timezone.utc).isoformat(),
                        finished_at=None, summary=None)
    try:
        from app.ingestion.universe import ingest_universe
        from app.universe.constituents import load_universe
        tickers = load_universe(refresh=req.refresh_constituents)
        summary = await ingest_universe(
            tickers, skip_fresh_days=req.skip_fresh_days, max_names=req.max_names)
        _refresh_job["summary"] = {k: v for k, v in summary.items() if k != "errors"}
        _refresh_job["error_count"] = len(summary.get("errors", {}))
    except Exception as e:
        logger.exception("[universe] refresh job failed")
        _refresh_job["summary"] = {"error": str(e)}
    finally:
        _refresh_job.update(running=False, finished_at=datetime.now(timezone.utc).isoformat())


@router.post("/refresh")
async def refresh(req: RefreshRequest):
    """Kick off a tier-1 batch ingest over the universe (background). One run at a time."""
    if _refresh_job["running"]:
        raise HTTPException(409, "A universe refresh is already running.")
    asyncio.create_task(_run_refresh(req))
    return {"status": "started",
            "note": f"Tier-1 ingest started (skip_fresh_days={req.skip_fresh_days}). "
                    "Poll /api/universe/status for progress."}


# ── Promote (background) ───────────────────────────────────────────────────────────────────────────
async def _run_promote(ticker: str) -> None:
    _promotions[ticker] = {"running": True, "steps": None,
                           "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None}
    try:
        from app.ingestion.universe import promote_to_watchlist
        res = await promote_to_watchlist(ticker)
        _promotions[ticker]["steps"] = res["steps"]
    except Exception as e:
        logger.exception("[universe] promote job failed for %s", ticker)
        _promotions[ticker]["steps"] = {"error": str(e)}
    finally:
        _promotions[ticker].update(running=False, finished_at=datetime.now(timezone.utc).isoformat())


@router.post("/promote/{ticker}")
async def promote(ticker: str, db: AsyncSession = Depends(get_db)):
    """Promote a universe name to the watchlist + run the full LLM pipeline (background)."""
    ticker = ticker.upper()
    if _promotions.get(ticker, {}).get("running"):
        raise HTTPException(409, f"{ticker} is already being promoted.")
    asyncio.create_task(_run_promote(ticker))
    return {"status": "started", "ticker": ticker,
            "note": "Full pipeline running (ingest → LLM archetype → agents → score → decision). "
                    "Poll /api/universe/status or the stock page."}
