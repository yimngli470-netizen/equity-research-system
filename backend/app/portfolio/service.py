"""Portfolio service (roadmap 6.2) — CRUD + the computed book the sizing engine reasons about.

`compute_book` turns the holdings ledger + cash into honest weights: each name as a fraction of
TOTAL capital (not just of equity), sector exposure, unrealized P&L, a portfolio beta vs SPY, and a
return-correlation matrix among holdings. `correlation_with_book` scores how a candidate co-moves
with what you already own — the real concentration input that replaces the old same-sector name
count. All deterministic, from data already in the DB (prices + SPY benchmark + financials).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import PortfolioAccount, PortfolioPosition
from app.models.price import DailyPrice
from app.models.stock import Stock
from app.valuation_model.wacc import compute_beta

logger = logging.getLogger(__name__)

_MIN_CORR_OVERLAP = 40  # trading days of common history before a correlation is meaningful


# ── CRUD ───────────────────────────────────────────────────────────────────────────────────────
async def get_account(db: AsyncSession) -> PortfolioAccount:
    """The cash singleton — created on first access (cash 0)."""
    acct = (await db.execute(select(PortfolioAccount).order_by(PortfolioAccount.id).limit(1))).scalar_one_or_none()
    if acct is None:
        acct = PortfolioAccount(cash=0.0, label="default")
        db.add(acct)
        await db.commit()
        await db.refresh(acct)
    return acct


async def set_cash(db: AsyncSession, cash: float) -> PortfolioAccount:
    acct = await get_account(db)
    acct.cash = float(cash)
    await db.commit()
    await db.refresh(acct)
    return acct


async def list_positions(db: AsyncSession) -> list[PortfolioPosition]:
    return list((await db.execute(select(PortfolioPosition).order_by(PortfolioPosition.ticker))).scalars().all())


async def upsert_position(
    db: AsyncSession, ticker: str, shares: float,
    cost_basis: float | None = None, opened_date: date | None = None, notes: str | None = None,
) -> PortfolioPosition:
    """Add or update a holding (one row per ticker). shares<=0 deletes it."""
    ticker = ticker.upper()
    pos = (await db.execute(select(PortfolioPosition).where(PortfolioPosition.ticker == ticker))).scalar_one_or_none()
    if shares is not None and shares <= 0:
        if pos:
            await db.delete(pos)
            await db.commit()
        return pos  # type: ignore[return-value]
    if pos is None:
        pos = PortfolioPosition(ticker=ticker, shares=shares, cost_basis=cost_basis,
                                opened_date=opened_date, notes=notes)
        db.add(pos)
    else:
        pos.shares = shares
        if cost_basis is not None:
            pos.cost_basis = cost_basis
        if opened_date is not None:
            pos.opened_date = opened_date
        if notes is not None:
            pos.notes = notes
    await db.commit()
    await db.refresh(pos)
    return pos


async def delete_position(db: AsyncSession, ticker: str) -> bool:
    pos = (await db.execute(select(PortfolioPosition).where(PortfolioPosition.ticker == ticker.upper()))).scalar_one_or_none()
    if pos is None:
        return False
    await db.delete(pos)
    await db.commit()
    return True


# ── Pricing + returns ────────────────────────────────────────────────────────────────────────────
async def _latest_close(db: AsyncSession, ticker: str) -> tuple[float | None, date | None]:
    row = (
        await db.execute(
            select(DailyPrice.close, DailyPrice.date).where(DailyPrice.ticker == ticker)
            .order_by(DailyPrice.date.desc()).limit(1)
        )
    ).first()
    return (float(row[0]), row[1]) if row and row[0] is not None else (None, None)


async def _daily_returns(db: AsyncSession, ticker: str, limit: int = 400) -> dict[date, float]:
    rows = (
        await db.execute(
            select(DailyPrice.date, DailyPrice.adj_close).where(DailyPrice.ticker == ticker)
            .order_by(DailyPrice.date.asc())
        )
    ).all()
    out: dict[date, float] = {}
    prev = None
    for d, px in rows[-limit:]:
        if prev is not None and prev > 0 and px is not None:
            out[d] = px / prev - 1.0
        prev = px if px is not None else prev
    return out


def _corr(a: dict[date, float], b: dict[date, float]) -> float | None:
    common = sorted(set(a) & set(b))
    if len(common) < _MIN_CORR_OVERLAP:
        return None
    import numpy as np
    va = np.array([a[d] for d in common]); vb = np.array([b[d] for d in common])
    if va.std() == 0 or vb.std() == 0:
        return None
    return float(np.corrcoef(va, vb)[0, 1])


# ── Book ──────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class PositionView:
    ticker: str
    name: str | None
    sector: str | None
    archetype: str | None
    shares: float
    cost_basis: float | None
    last_price: float | None
    market_value: float | None
    weight: float | None              # fraction of TOTAL book (incl. cash)
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    beta: float | None
    opened_date: str | None
    notes: str | None


@dataclass
class BookView:
    positions: list[dict] = field(default_factory=list)
    cash: float = 0.0
    total_invested: float = 0.0
    total_book: float = 0.0
    cash_pct: float = 0.0
    n_positions: int = 0
    sector_weights: dict = field(default_factory=dict)   # sector -> fraction of total book
    portfolio_beta: float | None = None                  # weighted (incl. cash drag)
    top_correlations: list[dict] = field(default_factory=list)  # most-correlated holding pairs
    total_unrealized_pnl: float | None = None
    as_of: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


async def compute_book(db: AsyncSession, with_correlations: bool = True) -> BookView:
    """The full computed book: weights, sector exposure, P&L, portfolio beta, holding correlations."""
    positions = await list_positions(db)
    acct = await get_account(db)
    cash = float(acct.cash or 0.0)

    views: list[PositionView] = []
    returns: dict[str, dict[date, float]] = {}
    as_of: date | None = None
    for p in positions:
        stock = await db.get(Stock, p.ticker)
        last, d = await _latest_close(db, p.ticker)
        if d and (as_of is None or d > as_of):
            as_of = d
        mv = (p.shares * last) if last is not None else None
        pnl = pnl_pct = None
        if last is not None and p.cost_basis:
            pnl = (last - p.cost_basis) * p.shares
            pnl_pct = (last / p.cost_basis - 1.0) if p.cost_basis else None
        beta = await compute_beta(db, p.ticker)
        views.append(PositionView(
            ticker=p.ticker, name=stock.name if stock else None,
            sector=stock.sector if stock else None, archetype=stock.archetype if stock else None,
            shares=p.shares, cost_basis=p.cost_basis, last_price=last, market_value=mv,
            weight=None, unrealized_pnl=pnl, unrealized_pnl_pct=pnl_pct, beta=beta,
            opened_date=str(p.opened_date) if p.opened_date else None, notes=p.notes,
        ))
        if with_correlations:
            returns[p.ticker] = await _daily_returns(db, p.ticker)

    total_invested = sum(v.market_value for v in views if v.market_value) or 0.0
    total_book = total_invested + cash

    # Weights of TOTAL book; sector exposure; portfolio beta (cash contributes 0 → beta drag).
    sector_weights: dict[str, float] = {}
    pbeta_num = 0.0
    pbeta_ok = total_book > 0
    for v in views:
        if v.market_value and total_book > 0:
            v.weight = v.market_value / total_book
            sector_weights[v.sector or "Unclassified"] = sector_weights.get(v.sector or "Unclassified", 0.0) + v.weight
            if v.beta is not None:
                pbeta_num += v.weight * v.beta
            else:
                pbeta_ok = False  # an unknown beta makes the portfolio beta incomplete

    total_pnl = sum(v.unrealized_pnl for v in views if v.unrealized_pnl is not None) if views else None

    # Correlation pairs among holdings (for the risk view) — top by |corr|.
    top_corr: list[dict] = []
    if with_correlations and len(views) >= 2:
        tickers = [v.ticker for v in views]
        for i in range(len(tickers)):
            for j in range(i + 1, len(tickers)):
                c = _corr(returns[tickers[i]], returns[tickers[j]])
                if c is not None:
                    top_corr.append({"a": tickers[i], "b": tickers[j], "corr": round(c, 2)})
        top_corr.sort(key=lambda x: abs(x["corr"]), reverse=True)
        top_corr = top_corr[:8]

    return BookView(
        positions=[asdict(v) for v in views],
        cash=round(cash, 2),
        total_invested=round(total_invested, 2),
        total_book=round(total_book, 2),
        cash_pct=round(cash / total_book, 4) if total_book > 0 else 0.0,
        n_positions=len(views),
        sector_weights={k: round(v, 4) for k, v in sorted(sector_weights.items(), key=lambda x: -x[1])},
        portfolio_beta=round(pbeta_num, 3) if (pbeta_ok and total_book > 0) else None,
        top_correlations=top_corr,
        total_unrealized_pnl=round(total_pnl, 2) if total_pnl is not None else None,
        as_of=str(as_of) if as_of else None,
    )


@dataclass
class BookConcentration:
    """The sizing inputs derived from the real book for a candidate name."""
    held_weight: float           # current weight of this name in the book (0 if not held)
    sector_weight: float         # current book weight already in this name's sector (excl. the name)
    corr_with_book: float | None # weighted-avg return correlation vs the rest of the book
    total_book: float
    n_positions: int


async def book_concentration(db: AsyncSession, ticker: str) -> BookConcentration:
    """Compute the candidate's real-book concentration inputs for sizing (sector weight + correlation)."""
    ticker = ticker.upper()
    book = await compute_book(db, with_correlations=False)
    stock = await db.get(Stock, ticker)
    sector = stock.sector if stock else None

    held_weight = 0.0
    sector_weight = 0.0
    for p in book.positions:
        if p["ticker"] == ticker:
            held_weight = p["weight"] or 0.0
            continue
        if sector and p["sector"] == sector:
            sector_weight += p["weight"] or 0.0

    # Correlation of the candidate vs the rest of the book, weighted by each holding's book weight.
    corr_with_book: float | None = None
    others = [p for p in book.positions if p["ticker"] != ticker and (p["weight"] or 0) > 0]
    if others:
        cand_ret = await _daily_returns(db, ticker)
        num = denom = 0.0
        for p in others:
            c = _corr(cand_ret, await _daily_returns(db, p["ticker"]))
            if c is not None:
                num += p["weight"] * c
                denom += p["weight"]
        if denom > 0:
            corr_with_book = round(num / denom, 3)

    return BookConcentration(
        held_weight=round(held_weight, 4), sector_weight=round(sector_weight, 4),
        corr_with_book=corr_with_book, total_book=book.total_book, n_positions=book.n_positions,
    )
