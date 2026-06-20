"""Peer-closeness weights (roadmap 1.2) — measured, not LLM-opined.

For each ticker we measure how close every other name is, as a blend of:
  (a) fundamental-feature distance — standardized distance between quant profiles (1.1);
  (b) trailing return correlation — how much the two stocks co-move;
  (c) business-description embedding cosine — ML M1, a pluggable hook here (None until the
      embedding provider is wired; see ANALYST_ROADMAP.md §4a / open decision #5).

An LLM may *propose* which names are candidate peers, but the closeness WEIGHT is a measurement —
that's the whole point: "NVDA→AMD > NVDA→ASML" should be a reproducible number, not an opinion.
The universe is every ticker we have data for (quant profile + prices); expanding it with curated
out-of-watchlist peers is a follow-up (needs ingesting their data).

Pure stats (numpy). No LLM, no network. Cross-sectional: recompute once after all tickers ingest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.measurement.profile import QuantProfile, compute_quant_profile
from app.models.peer import PeerWeight
from app.models.price import DailyPrice
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# Quant-profile fields used for the fundamental-distance vector (all fractions, comparable units).
_FEATURES = (
    "revenue_growth_mean", "revenue_growth_std", "revenue_max_drawdown",
    "gross_margin_mean", "gross_margin_std",
    "operating_margin_mean", "operating_margin_std", "net_margin_mean",
    "loss_quarter_pct", "capex_intensity_mean",
)

# Blend weights over the available components. Embedding is 0 until M1 lands; when it does, rebalance
# (e.g. fundamental .4 / returns .3 / embedding .3). Missing components are dropped and the rest
# renormalized, so a name with no return overlap still gets a fundamental-only weight.
_COMPONENT_WEIGHTS = {"fundamental": 0.5, "returns": 0.5, "embedding": 0.0}

_MIN_RETURN_OVERLAP = 60  # trading days of common history required to trust a correlation


@dataclass
class _Universe:
    tickers: list[str]
    z: np.ndarray                       # (n_tickers, n_features) standardized, mean-imputed
    returns: dict[str, dict[date, float]]  # ticker -> {date: daily return}


def _standardize(profiles: dict[str, QuantProfile]) -> tuple[list[str], np.ndarray]:
    """Z-score each feature across the universe; missing values imputed to the mean (z=0)."""
    tickers = sorted(profiles)
    raw = np.full((len(tickers), len(_FEATURES)), np.nan)
    for i, t in enumerate(tickers):
        d = profiles[t].to_dict()
        for j, f in enumerate(_FEATURES):
            if d.get(f) is not None:
                raw[i, j] = d[f]

    z = np.zeros_like(raw)
    for j in range(len(_FEATURES)):
        col = raw[:, j]
        present = col[~np.isnan(col)]
        if present.size == 0:
            continue
        mean = present.mean()
        std = present.std()
        if std == 0:
            continue
        z[:, j] = np.where(np.isnan(col), 0.0, (col - mean) / std)  # NaN -> mean -> z=0
    return tickers, z


def _fundamental_sim(zi: np.ndarray, zj: np.ndarray) -> float:
    """Gaussian kernel on the RMS per-feature z-distance → (0, 1], 1.0 when identical."""
    rms = float(np.sqrt(np.mean((zi - zj) ** 2)))
    return float(np.exp(-0.5 * rms * rms))


def _return_corr(a: dict[date, float], b: dict[date, float]) -> float | None:
    """Pearson correlation of daily returns over common dates; None if too little overlap."""
    common = sorted(set(a) & set(b))
    if len(common) < _MIN_RETURN_OVERLAP:
        return None
    va = np.array([a[d] for d in common])
    vb = np.array([b[d] for d in common])
    if va.std() == 0 or vb.std() == 0:
        return None
    return float(np.corrcoef(va, vb)[0, 1])


def _blend(fundamental: float | None, corr: float | None, embedding: float | None) -> float:
    """Weighted mean of available components; returns use max(0, corr) (anti-correlation ≠ close)."""
    parts = {
        "fundamental": fundamental,
        "returns": None if corr is None else max(0.0, corr),
        "embedding": embedding,
    }
    num = den = 0.0
    for name, val in parts.items():
        w = _COMPONENT_WEIGHTS[name]
        if val is not None and w > 0:
            num += w * val
            den += w
    return round(num / den, 4) if den > 0 else 0.0


async def _load_universe(db: AsyncSession) -> _Universe | None:
    """Build the comparison universe: every ticker with a quant profile, plus its return series."""
    tickers = [r[0] for r in (await db.execute(select(Stock.ticker))).all()]
    profiles: dict[str, QuantProfile] = {}
    for t in tickers:
        p = await compute_quant_profile(db, t)
        if p is not None:
            profiles[t] = p
    if len(profiles) < 2:
        return None

    order, z = _standardize(profiles)

    returns: dict[str, dict[date, float]] = {}
    for t in order:
        rows = (
            await db.execute(
                select(DailyPrice.date, DailyPrice.adj_close)
                .where(DailyPrice.ticker == t)
                .order_by(DailyPrice.date.asc())
            )
        ).all()
        series: dict[date, float] = {}
        prev = None
        for d, px in rows:
            if prev is not None and prev > 0 and px is not None:
                series[d] = px / prev - 1.0
            prev = px
        returns[t] = series

    return _Universe(tickers=order, z=z, returns=returns)


def _pairs_for(uni: _Universe, ticker: str) -> list[PeerWeight] | None:
    if ticker not in uni.tickers:
        return None
    i = uni.tickers.index(ticker)
    today = date.today()
    out: list[PeerWeight] = []
    for j, peer in enumerate(uni.tickers):
        if peer == ticker:
            continue
        f_sim = _fundamental_sim(uni.z[i], uni.z[j])
        corr = _return_corr(uni.returns[ticker], uni.returns[peer])
        weight = _blend(f_sim, corr, None)
        out.append(PeerWeight(
            ticker=ticker, peer=peer, weight=weight,
            fundamental_sim=round(f_sim, 4),
            return_corr=None if corr is None else round(corr, 4),
            embedding_sim=None, as_of=today,
        ))
    out.sort(key=lambda p: p.weight, reverse=True)
    return out


async def compute_peer_weights(db: AsyncSession, ticker: str) -> list[PeerWeight]:
    """Closeness of every other universe name to `ticker`, sorted by weight desc (not persisted)."""
    uni = await _load_universe(db)
    if uni is None:
        return []
    return _pairs_for(uni, ticker.upper()) or []


async def recompute_peer_weights(db: AsyncSession) -> int:
    """Recompute all pairwise peer weights across the universe and upsert. Returns row count."""
    uni = await _load_universe(db)
    if uni is None:
        logger.info("[peers] universe too small to compute peer weights")
        return 0

    rows: list[dict] = []
    for t in uni.tickers:
        for pw in _pairs_for(uni, t) or []:
            rows.append({
                "ticker": pw.ticker, "peer": pw.peer, "weight": pw.weight,
                "fundamental_sim": pw.fundamental_sim, "return_corr": pw.return_corr,
                "embedding_sim": pw.embedding_sim, "as_of": pw.as_of,
            })
    if not rows:
        return 0

    # Chunk the upsert: a single multi-row INSERT is capped at asyncpg's 32767 bound parameters
    # (≈ 4680 rows × 7 cols), which the full pairwise grid exceeds once the universe is large.
    _COLS = ("weight", "fundamental_sim", "return_corr", "embedding_sim", "as_of")
    CHUNK = 2000  # 2000 × 7 = 14k params, safely under the limit
    for i in range(0, len(rows), CHUNK):
        batch = rows[i:i + CHUNK]
        stmt = insert(PeerWeight).values(batch)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_peer_ticker_peer",
            set_={c: getattr(stmt.excluded, c) for c in _COLS},
        )
        await db.execute(stmt)
    await db.commit()
    logger.info("[peers] recomputed %d peer-weight rows across %d names", len(rows), len(uni.tickers))
    return len(rows)
