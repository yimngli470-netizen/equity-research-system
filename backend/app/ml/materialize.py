"""Materialize the point-in-time panel into the DB store (M4 stage 3).

    docker compose exec backend python -m app.ml.materialize                      # 63d/63d, PIT
    docker compose exec backend python -m app.ml.materialize --rebalance 21      # monthly grid
    docker compose exec backend python -m app.ml.materialize --label "pre-M4" --no-pit

Each run writes ONE immutable PanelVersion (the recipe) + its PanelRows, and prints the version id.
Training/eval then pins that id (`python -m app.ml.run --panel-version N`), which is what makes a
result reproducible: the exact rows a model saw are queryable long after the underlying prices/
financials tables have moved on.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.run import _universe_tickers
from app.database import async_session
from app.ml.panel import FEATURE_COLS, LABEL_COL, build_panel
from app.models.panel import PanelRow, PanelVersion

logger = logging.getLogger(__name__)

_CHUNK = 2000  # rows per INSERT — stay well under asyncpg's 32767 bind-parameter cap


async def materialize_panel(
    db: AsyncSession,
    *,
    horizon_days: int = 63,
    rebalance_days: int = 63,
    pit: bool = True,
    label: str | None = None,
) -> PanelVersion:
    """Build the panel and persist it as a new immutable version. Returns the PanelVersion row."""
    membership: dict | None = None
    if pit:
        from app.universe.history import load_history
        membership = load_history()

    tickers = await _universe_tickers(membership)
    df = await build_panel(db, tickers, horizon_days=horizon_days,
                           rebalance_days=rebalance_days, membership=membership)

    version = PanelVersion(
        label=label,
        params={
            "horizon_days": horizon_days,
            "rebalance_days": rebalance_days,
            "universe": "point-in-time" if membership is not None else "current-snapshot",
            "gating": "filed_date|75d-fallback",
            "n_tickers": len(tickers),
            "feature_cols": FEATURE_COLS,
            "label_col": LABEL_COL,
        },
        row_count=len(df),
    )
    db.add(version)
    await db.flush()  # get version.id

    records = [
        {
            "version_id": version.id,
            "ticker": r["ticker"],
            "date": date.fromisoformat(r["date"]),
            "features": {c: r[c] for c in FEATURE_COLS if pd.notna(r.get(c))},
            "label": float(r[LABEL_COL]),
        }
        for r in df.to_dict("records")
    ]
    from sqlalchemy import insert
    for i in range(0, len(records), _CHUNK):
        await db.execute(insert(PanelRow), records[i:i + _CHUNK])
    await db.commit()
    logger.info("[panel] materialized version %d: %d rows (%s universe)",
                version.id, len(records), version.params["universe"])
    return version


async def load_panel_version(db: AsyncSession, version_id: int) -> tuple[pd.DataFrame, dict]:
    """Read a materialized version back as the same flat DataFrame `build_panel` produces
    (ticker · date-iso · features · label). Returns (df, params)."""
    version = await db.get(PanelVersion, version_id)
    if version is None:
        raise ValueError(f"panel version {version_id} not found — run app.ml.materialize first")
    rows = (
        await db.execute(select(PanelRow).where(PanelRow.version_id == version_id)
                         .order_by(PanelRow.date, PanelRow.ticker))
    ).scalars().all()
    feature_cols = version.params["feature_cols"]
    df = pd.DataFrame([
        {"ticker": r.ticker, "date": r.date.isoformat(),
         **{c: r.features.get(c) for c in feature_cols},
         version.params["label_col"]: r.label}
        for r in rows
    ])
    return df, version.params


async def _main(args: argparse.Namespace) -> None:
    async with async_session() as db:
        v = await materialize_panel(db, horizon_days=args.horizon, rebalance_days=args.rebalance,
                                    pit=not args.no_pit, label=args.label)
    print(f"panel version {v.id}: {v.row_count} rows · {v.params['universe']} universe · "
          f"{v.params['horizon_days']}d horizon / {v.params['rebalance_days']}d rebalance")


def main() -> None:
    ap = argparse.ArgumentParser(description="Materialize the point-in-time (X, y) panel to the DB.")
    ap.add_argument("--horizon", type=int, default=63)
    ap.add_argument("--rebalance", type=int, default=63)
    ap.add_argument("--label", type=str, default=None)
    ap.add_argument("--no-pit", action="store_true",
                    help="legacy current-snapshot universe (survivorship-biased)")
    args = ap.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
