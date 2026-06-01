"""Peer-relative normalization (roadmap 1.3) — the P1 fix.

The old normalizer scores every name on one fixed ruler: `forward_pe 10→60`, so MU's 9.1 P/E
clamps to ~1.0 "screaming cheap" regardless of context. That's meaningless — P/E 9 means one thing
for a memory cyclical at peak earnings and another for a platform. Here we instead score each
valuation multiple by the subject's **weighted percentile within its peer set** (the closeness
weights from 1.2): "cheaper than X% of your weighted peers", not "cheap on an absolute scale".

Lower-is-better multiples are inverted (cheap → high score). Non-positive multiples (negative/no
earnings) score 0.0, as before. When too few peers carry a metric we **fall back to the absolute
norm** for that one metric (graceful degradation), so this never scores worse than the old path.

NOTE: peer-relative valuation fixes P1 (the absolute ruler). It does NOT by itself fix the
cyclical *peak-earnings* trap — MU's forward P/E is low partly because E is at a cycle peak. That
needs normalized/mid-cycle earnings (Phase 2.2). This makes the comparison fair; it doesn't make
the denominator right.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.peer import PeerWeight
from app.models.valuation import Valuation
from app.quant.normalizer import normalize_features

logger = logging.getLogger(__name__)

# Valuation-category feature -> the Valuation column to read peer values from.
_FEATURE_COLUMN = {
    "forward_pe": "forward_pe",
    "trailing_pe": "trailing_pe",
    "peg_ratio": "peg_ratio",
    "price_to_sales": "price_to_sales",
    "price_to_book": "price_to_book",
    "ev_to_revenue": "ev_to_revenue",
    "ev_to_ebitda": "ev_to_ebitda",
    "earnings_growth": "earnings_growth",
    "revenue_growth_fwd": "revenue_growth",
}

# Lower is better (cheaper) → invert; these are also positive-only (≤0 is meaningless).
_INVERT = {
    "forward_pe", "trailing_pe", "peg_ratio", "price_to_sales",
    "price_to_book", "ev_to_revenue", "ev_to_ebitda",
}

TOP_K = 8          # compare against the K closest peers (the weighting already down-ranks the rest)
MIN_PEERS = 4      # below this many peers carrying the metric, fall back to the absolute norm


@dataclass
class PeerNormResult:
    normalized: dict[str, float | None]
    n_peer_relative: int      # features scored vs peers
    n_absolute: int           # features that fell back to the absolute ruler
    peer_count: int           # peers used


def _weighted_percentile(subject: float, pairs: list[tuple[float, float]], invert: bool) -> float:
    """Fraction of peer-weight the subject sits above (ties count half). Inverted for cheap-is-good."""
    total = sum(w for _, w in pairs)
    if total <= 0:
        return 0.5
    below = sum(w for v, w in pairs if v < subject)
    equal = sum(w for v, w in pairs if v == subject)
    pct = (below + 0.5 * equal) / total
    return round(1.0 - pct if invert else pct, 4)


async def _load_peers(db: AsyncSession, ticker: str) -> dict[str, float]:
    """Top-K peer weights for `ticker` (peer -> weight), highest first."""
    rows = (
        await db.execute(
            select(PeerWeight.peer, PeerWeight.weight)
            .where(PeerWeight.ticker == ticker.upper(), PeerWeight.weight > 0)
            .order_by(PeerWeight.weight.desc())
            .limit(TOP_K)
        )
    ).all()
    return {p: w for p, w in rows}


async def _latest_valuations(db: AsyncSession, tickers: list[str]) -> dict[str, Valuation]:
    """Most recent Valuation row per ticker."""
    out: dict[str, Valuation] = {}
    for t in tickers:
        v = (
            await db.execute(
                select(Valuation).where(Valuation.ticker == t)
                .order_by(Valuation.date.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if v is not None:
            out[t] = v
    return out


async def peer_relative_valuation(
    db: AsyncSession, ticker: str, raw: dict[str, float | None]
) -> PeerNormResult:
    """Peer-relative scores for the valuation category, with per-metric absolute fallback."""
    ticker = ticker.upper()
    weights = await _load_peers(db, ticker)

    # No peer graph yet → degrade gracefully to the absolute ruler for the whole category.
    if not weights:
        logger.info("[peer-norm] %s: no peer weights; using absolute valuation norms", ticker)
        return PeerNormResult(normalize_features("valuation", raw), 0, len(raw), 0)

    peer_vals = await _latest_valuations(db, list(weights))
    absolute = normalize_features("valuation", raw)  # computed once for fallback

    result: dict[str, float | None] = {}
    n_rel = n_abs = 0
    for name, subject in raw.items():
        col = _FEATURE_COLUMN.get(name)
        invert = name in _INVERT

        if subject is None or col is None:
            result[name] = absolute.get(name)
            n_abs += 1
            continue
        if invert and subject <= 0:           # negative/no earnings → not "cheap"
            result[name] = 0.0
            n_rel += 1
            continue

        pairs = []
        for peer, w in weights.items():
            pv = getattr(peer_vals.get(peer), col, None) if peer in peer_vals else None
            if pv is None:
                continue
            if invert and pv <= 0:             # drop peers with meaningless multiples
                continue
            pairs.append((pv, w))

        if len(pairs) < MIN_PEERS:
            result[name] = absolute.get(name)  # too thin to be peer-relative
            n_abs += 1
        else:
            result[name] = _weighted_percentile(subject, pairs, invert)
            n_rel += 1

    logger.info("[peer-norm] %s valuation: %d peer-relative, %d absolute-fallback (%d peers)",
                ticker, n_rel, n_abs, len(peer_vals))
    return PeerNormResult(result, n_rel, n_abs, len(peer_vals))
