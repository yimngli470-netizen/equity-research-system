"""Tier-1 universe ingest (roadmap 6.1d) — batch-screen the S&P 500 + NASDAQ-100 at ~zero LLM.

The watchlist path (`ingest_ticker`) is deep and partly LLM-driven: bootstrap (KPI defs + IR
discovery), transcripts, KPI extraction, grounded-LLM archetype. That's right for ~13 names you've
chosen to cover, wrong for ~520 you're only screening. So tier-1 runs a deliberately slim path —
**prices + EDGAR financials + valuation snapshot + a RULE-BASED archetype** — and nothing else. No
transcripts, no agents, no LLM. A name earns the full pipeline only when promoted (6.1e).

The output is the same `stock_scores` the watchlist uses, so the existing screen/normalizer/peer
machinery works unchanged — a universe name simply has neutral AI categories (no agent reports) and
a real, peer-relative hard-feature score. With ~520 names the peer pools finally become meaningful
(the roadmap's "UBER gets semiconductor comps" problem dissolves).

Idempotent + resumable: a name with fresh financials is skipped, so a re-run after a partial failure
only touches what's missing. Per-name failures are collected, never fatal to the batch.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.ingestion.edgar import ingest_financials_edgar
from app.ingestion.fundamentals import ingest_financials, ingest_valuation
from app.ingestion.pipeline import IngestionResult, _update_stock_info
from app.ingestion.prices import ingest_benchmark_prices, ingest_prices
from app.measurement.archetype_rules import classify_archetype_rules
from app.measurement.profile import compute_quant_profile
from app.models.financial import Financial
from app.models.stock import Stock

logger = logging.getLogger(__name__)


async def ensure_universe_stock(db: AsyncSession, ticker: str) -> Stock:
    """Get-or-create the Stock row for a tier-1 name (coverage_tier="universe", not on the watchlist)."""
    ticker = ticker.upper()
    stock = await db.get(Stock, ticker)
    if stock is None:
        stock = Stock(ticker=ticker, name=ticker, coverage_tier="universe", active=False,
                      added_date=date.today())
        db.add(stock)
        await db.commit()
    return stock


async def _classify_rules(db: AsyncSession, ticker: str) -> str | None:
    """Assign the deterministic provisional archetype. Never overwrites a grounded-LLM label."""
    stock = await db.get(Stock, ticker)
    if stock is None:
        return None
    if stock.archetype and stock.archetype_source == "llm":
        return stock.archetype  # a promoted name keeps its LLM label

    profile = await compute_quant_profile(db, ticker)
    if profile is None:
        return None
    r = classify_archetype_rules(profile, stock.sector, stock.industry)
    stock.archetype = r.archetype
    stock.archetype_source = "rules"
    stock.archetype_features = profile.to_dict()
    stock.archetype_rationale = f"[rules/{r.confidence}] {r.rationale}"
    stock.archetype_as_of = date.today()
    await db.commit()
    return r.archetype


async def _has_fresh_financials(db: AsyncSession, ticker: str, within_days: int) -> bool:
    """True if we already ingested financials for this name recently — the resumability gate."""
    cutoff = date.today() - timedelta(days=within_days)
    row = (
        await db.execute(
            select(Financial.as_of).where(Financial.ticker == ticker)
            .order_by(Financial.period_end_date.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None and row >= cutoff


async def ingest_universe_ticker(ticker: str) -> IngestionResult:
    """Slim tier-1 ingest for ONE name: prices + EDGAR financials + valuation + rule-archetype."""
    ticker = ticker.upper()
    result = IngestionResult(ticker=ticker)

    async with async_session() as db:
        await ensure_universe_stock(db, ticker)

    # Name/sector/industry from yfinance (sector breaks the `financial` archetype case + display).
    await _update_stock_info(ticker)

    async with async_session() as db:
        try:
            result.prices = await ingest_prices(db, ticker)
        except Exception as e:
            logger.warning("[universe] prices failed for %s: %s", ticker, e)
            result.errors.append(f"prices: {e}")

        try:
            result.financials = await ingest_financials_edgar(db, ticker)
        except Exception as e:
            logger.warning("[universe] EDGAR failed for %s (%s); trying yfinance", ticker, e)
            try:
                result.financials = await ingest_financials(db, ticker)
            except Exception as e2:
                result.errors.append(f"financials: {e2}")

        try:
            result.valuation = await ingest_valuation(db, ticker)
        except Exception as e:
            logger.warning("[universe] valuation failed for %s: %s", ticker, e)
            result.errors.append(f"valuation: {e}")

        try:
            result.archetype = await _classify_rules(db, ticker)
            if result.archetype is None:
                result.warnings.append(f"{ticker}: too little history for a provisional archetype.")
        except Exception as e:
            result.errors.append(f"archetype: {e}")

    return result


async def ingest_universe(
    tickers: list[str] | None = None,
    *,
    skip_fresh_days: int = 7,
    max_names: int | None = None,
    score: bool = True,
) -> dict:
    """Batch tier-1 ingest + score across the universe.

    Args:
        tickers: names to ingest; defaults to the committed S&P 500 + NASDAQ-100 snapshot.
        skip_fresh_days: skip a name whose financials were ingested within this many days
            (resumability — a re-run only touches what's missing). 0 forces a full re-ingest.
        max_names: cap for a partial / smoke run.
        score: recompute peer weights + composite scores after ingest (the screen output).
    """
    if tickers is None:
        from app.universe.constituents import load_universe
        tickers = load_universe()
    if max_names is not None:
        tickers = tickers[:max_names]

    logger.info("[universe] tier-1 ingest over %d names (skip_fresh_days=%d)", len(tickers), skip_fresh_days)
    ingested, skipped, failed = 0, 0, 0
    errors: dict[str, list[str]] = {}

    for i, t in enumerate(tickers, 1):
        t = t.upper()
        if skip_fresh_days > 0:
            async with async_session() as db:
                if await _has_fresh_financials(db, t, skip_fresh_days):
                    # Network ingest is fresh — skip it, but still re-run the (free) rule classifier
                    # so archetype-threshold tuning propagates without a full re-ingest.
                    try:
                        await _classify_rules(db, t)
                    except Exception:
                        logger.warning("[universe] reclassify failed for %s", t)
                    skipped += 1
                    continue
        try:
            r = await ingest_universe_ticker(t)
            ingested += 1
            if r.errors:
                errors[t] = r.errors
                if r.financials == 0:
                    failed += 1
        except Exception as e:
            logger.exception("[universe] %s ingest crashed", t)
            failed += 1
            errors[t] = [str(e)]
        if i % 25 == 0:
            logger.info("[universe] progress %d/%d (ingested=%d skipped=%d failed=%d)",
                        i, len(tickers), ingested, skipped, failed)

    # SPY benchmark once for the batch (grading scores theses benchmark-relative).
    try:
        async with async_session() as db:
            await ingest_benchmark_prices(db)
    except Exception as e:
        logger.warning("[universe] benchmark ingest failed: %s", e)

    scored = 0
    if score:
        # Peer weights are CROSS-SECTIONAL — recompute once over the whole universe, then score.
        try:
            from app.measurement.peers import recompute_peer_weights
            async with async_session() as db:
                await recompute_peer_weights(db)
        except Exception:
            logger.exception("[universe] peer-weight recompute failed")
        scored = await score_universe(tickers)

    summary = {"requested": len(tickers), "ingested": ingested, "skipped": skipped,
               "failed": failed, "scored": scored, "errors": errors}
    logger.info("[universe] done: %s", {k: v for k, v in summary.items() if k != "errors"})
    return summary


async def promote_to_watchlist(ticker: str) -> dict:
    """Tier-2 transition (6.1e): a screened universe name graduates to full coverage.

    Flips the name to the watchlist, then runs the SAME full pipeline a watchlist name gets —
    deep ingest (transcripts/KPI), a grounded-LLM archetype that UPGRADES the provisional rule
    label, all agents (debate + judge), scoring, and the decision (price target + journal). This is
    the only place tier-1 spends LLM, and only because the user asked for this one name. Pull model
    intact: promotion is an explicit act, never automatic.
    """
    ticker = ticker.upper()
    async with async_session() as db:
        stock = await db.get(Stock, ticker)
        if stock is None:
            stock = Stock(ticker=ticker, name=ticker)
            db.add(stock)
        stock.coverage_tier = "watchlist"
        stock.active = True
        await db.commit()

    steps: dict[str, str] = {}
    # 1) Full ingest (bootstrap + transcripts + KPI + everything the watchlist gets).
    try:
        from app.ingestion.pipeline import ingest_ticker
        await ingest_ticker(ticker)
        steps["ingest"] = "ok"
    except Exception as e:
        logger.exception("[promote] ingest failed for %s", ticker)
        steps["ingest"] = f"error: {e}"

    # 2) Upgrade the provisional rule archetype to a grounded-LLM label (force past the rules label).
    try:
        from app.ingestion.archetype import classify_archetype
        async with async_session() as db:
            res = await classify_archetype(db, ticker, force=True)
        steps["archetype"] = f"{res.status}:{res.archetype}"
    except Exception as e:
        logger.exception("[promote] archetype upgrade failed for %s", ticker)
        steps["archetype"] = f"error: {e}"

    # 3) Agents (forecast + dialectic + judge + validation), 4) score, 5) decision (PT + journal).
    try:
        from app.agents.orchestrator import run_all_agents
        await run_all_agents(ticker, mode="smart")
        steps["agents"] = "ok"
    except Exception as e:
        logger.exception("[promote] agents failed for %s", ticker)
        steps["agents"] = f"error: {e}"
    try:
        from app.scoring.calculator import calculate_score
        async with async_session() as db:
            await calculate_score(db, ticker)
        steps["score"] = "ok"
    except Exception as e:
        steps["score"] = f"error: {e}"
    try:
        from app.decision.engine import run_decision
        async with async_session() as db:
            await run_decision(db, ticker)
        steps["decision"] = "ok"
    except Exception as e:
        steps["decision"] = f"error: {e}"

    logger.info("[promote] %s -> watchlist: %s", ticker, steps)
    return {"ticker": ticker, "steps": steps}


async def score_universe(tickers: list[str]) -> int:
    """Compute the composite screen score for each name (hard features; neutral AI categories)."""
    from app.scoring.calculator import calculate_score

    scored = 0
    for t in tickers:
        t = t.upper()
        try:
            async with async_session() as db:
                await calculate_score(db, t)
            scored += 1
        except Exception as e:
            logger.warning("[universe] scoring failed for %s: %s", t, e)
    return scored
