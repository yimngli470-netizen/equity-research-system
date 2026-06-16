"""Universe constituents (roadmap 6.1c) — the S&P 500 + NASDAQ-100 screening universe (~520 names).

Two ways to get the list:
  • a COMMITTED snapshot (`constituents_snapshot.json`) — the default. Reproducible, offline, and the
    record of "what was in the index when" that the 6.3 backtest needs to avoid survivorship bias.
  • a LIVE refresh from Wikipedia's index tables — explicit, on demand (the 6.1e refresh endpoint),
    which also rewrites the snapshot so the new membership is captured with a date.

The pull model is preserved: nothing fetches on its own. `load_universe()` reads the snapshot;
`refresh_constituents()` is only called when the user asks to re-pull the universe.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_SNAPSHOT = Path(__file__).with_name("constituents_snapshot.json")

_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_NDX_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
_HEADERS = {"User-Agent": "Mozilla/5.0 (equity-research-system; personal research)"}


def _norm(symbol: str) -> str:
    """Wikipedia uses dotted class shares (BRK.B); yfinance/EDGAR want the hyphen form (BRK-B)."""
    return str(symbol).strip().upper().replace(".", "-")


def fetch_constituents() -> dict:
    """Pull both index membership lists live from Wikipedia. Network — used only on explicit refresh.

    Returns {"as_of", "sp500": [...], "nasdaq100": [...], "tickers": [union, sorted]}.
    """
    import pandas as pd
    import requests

    def _tables(url: str):
        html = requests.get(url, headers=_HEADERS, timeout=30).text
        return pd.read_html(io.StringIO(html))

    sp_tables = _tables(_SP500_URL)
    sp500 = sorted({_norm(s) for s in sp_tables[0]["Symbol"].astype(str)})

    nasdaq100: list[str] = []
    for t in _tables(_NDX_URL):
        cols = [str(c) for c in t.columns]
        col = next((c for c in ("Ticker", "Symbol") if c in cols), None)
        if col:
            nasdaq100 = sorted({_norm(s) for s in t[col].astype(str)})
            break
    if not nasdaq100:
        raise RuntimeError("could not locate the NASDAQ-100 constituents table on Wikipedia")

    union = sorted(set(sp500) | set(nasdaq100))
    logger.info("[universe] fetched %d S&P 500 + %d NASDAQ-100 = %d unique",
                len(sp500), len(nasdaq100), len(union))
    return {"as_of": date.today().isoformat(), "sp500": sp500,
            "nasdaq100": nasdaq100, "tickers": union}


def refresh_constituents() -> dict:
    """Fetch live and overwrite the committed snapshot. Returns the new snapshot dict."""
    snap = fetch_constituents()
    _SNAPSHOT.write_text(json.dumps(snap, indent=2) + "\n")
    logger.info("[universe] snapshot written: %d names as_of %s", len(snap["tickers"]), snap["as_of"])
    return snap


def load_snapshot() -> dict:
    """Read the committed snapshot (no network). Raises if it hasn't been generated yet."""
    if not _SNAPSHOT.exists():
        raise FileNotFoundError(
            f"{_SNAPSHOT.name} not found — run refresh_constituents() once to generate it.")
    return json.loads(_SNAPSHOT.read_text())


def load_universe(refresh: bool = False) -> list[str]:
    """The screening universe as a sorted ticker list. Snapshot by default; live only if refresh."""
    snap = refresh_constituents() if refresh else load_snapshot()
    return snap["tickers"]


def membership(ticker: str) -> list[str]:
    """Which indices a ticker belongs to, per the snapshot — e.g. ['sp500', 'nasdaq100']."""
    snap = load_snapshot()
    t = _norm(ticker)
    return [idx for idx in ("sp500", "nasdaq100") if t in set(snap.get(idx, []))]
