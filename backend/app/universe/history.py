"""Historical S&P 500 membership (M4 stage 1) — who was in the index on any given date.

The live snapshot (`constituents.py`) only knows who is in the index NOW. A backtest built on
today's members quietly excludes every name that was removed along the way — bankruptcies,
delistings, decayed businesses — which flatters every historical result (survivorship bias).
This module answers the point-in-time question instead: `constituents_asof(date)`.

Membership is stored as INTERVALS, not sets: a ticker can enter, leave, and re-enter (AAL was a
member 1996–1997 and again 2015–2024), so each ticker maps to a list of [start, end) ranges with
`end = null` meaning "still a member".

Source (free): github.com/fja05680/sp500 — community-maintained S&P 500 membership-change history
built from S&P press releases / Wikipedia edits, back to 1996. Same pull-model pattern as the live
universe: a COMMITTED snapshot (`membership_history.json`) is the default — reproducible, offline —
and `refresh_membership_history()` re-pulls it only on explicit request.

Scope: S&P 500 only. No equivalent free interval history exists for the NASDAQ-100; the live
universe's NDX names are a small additive slice, and the backtest can still union the watchlist.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from bisect import bisect_right
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_SNAPSHOT = Path(__file__).with_name("membership_history.json")

_SOURCE_URL = "https://raw.githubusercontent.com/fja05680/sp500/master/sp500_ticker_start_end.csv"
_HEADERS = {"User-Agent": "Mozilla/5.0 (equity-research-system; personal research)"}


def _norm(symbol: str) -> str:
    """Dotted class shares (BRK.B) → the hyphen form (BRK-B) used by yfinance/EDGAR and our DB."""
    return str(symbol).strip().upper().replace(".", "-")


def refresh_membership_history() -> dict:
    """Fetch the interval CSV live and overwrite the committed snapshot. Network — explicit only.

    Snapshot shape: {"as_of", "source", "intervals": {ticker: [[start, end|null], ...]}}.
    """
    import requests

    text = requests.get(_SOURCE_URL, headers=_HEADERS, timeout=30).text
    intervals: dict[str, list[list[str | None]]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        t = _norm(row["ticker"])
        end = row["end_date"].strip() or None
        intervals.setdefault(t, []).append([row["start_date"].strip(), end])
    for spans in intervals.values():
        spans.sort(key=lambda s: s[0])

    snap = {"as_of": date.today().isoformat(), "source": _SOURCE_URL, "intervals": intervals}
    _SNAPSHOT.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n")
    n_open = sum(1 for spans in intervals.values() for s in spans if s[1] is None)
    logger.info("[universe] membership history written: %d tickers, %d intervals (%d open) as_of %s",
                len(intervals), sum(map(len, intervals.values())), n_open, snap["as_of"])
    return snap


def load_history() -> dict:
    """Read the committed snapshot (no network). Raises if it hasn't been generated yet."""
    if not _SNAPSHOT.exists():
        raise FileNotFoundError(
            f"{_SNAPSHOT.name} not found — run refresh_membership_history() once to generate it.")
    return json.loads(_SNAPSHOT.read_text())


def constituents_asof(asof: date, history: dict | None = None) -> list[str]:
    """S&P 500 members on `asof`, sorted. Interval test is [start, end): the removal date itself
    counts as OUT (index changes are effective at that day's open)."""
    hist = history if history is not None else load_history()
    d = asof.isoformat()
    return sorted(
        t for t, spans in hist["intervals"].items()
        if any(s[0] <= d and (s[1] is None or d < s[1]) for s in spans)
    )


def all_members_between(start: date, end: date, history: dict | None = None) -> list[str]:
    """Every ticker that was a member at ANY point in [start, end] — the backtest's full universe.
    (Loading data only for point-in-time members per date is done downstream; this is the superset
    to ingest/load.)"""
    hist = history if history is not None else load_history()
    lo, hi = start.isoformat(), end.isoformat()
    return sorted(
        t for t, spans in hist["intervals"].items()
        if any(s[0] <= hi and (s[1] is None or s[1] > lo) for s in spans)
    )


def membership_intervals(ticker: str, history: dict | None = None) -> list[list[str | None]]:
    """The raw [start, end|null] spans for one ticker ([] if never a member)."""
    hist = history if history is not None else load_history()
    return hist["intervals"].get(_norm(ticker), [])
