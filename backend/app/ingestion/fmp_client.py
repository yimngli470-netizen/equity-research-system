"""FMP (Financial Modeling Prep) API client.

Free tier: 250 calls/day. Uses the /stable/ API (the v3 endpoints were
deprecated 2025-08-31). Provides earnings transcripts, earnings calendar
(actuals + estimates), analyst estimates, and financial statements.
"""

import asyncio
import logging
from datetime import date, datetime

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://financialmodelingprep.com/stable"


class FMPRateLimitError(Exception):
    pass


class FMPClient:
    """Thin async wrapper around the FMP REST API."""

    def __init__(self):
        self.api_key = settings.fmp_api_key
        self._call_count = 0
        self._call_date: date = date.today()

    def _check_rate_limit(self):
        today = date.today()
        if today != self._call_date:
            self._call_count = 0
            self._call_date = today

        if self._call_count >= 250:
            raise FMPRateLimitError("FMP free tier limit reached (250 calls/day)")
        if self._call_count >= 200:
            logger.warning("FMP call count at %d/250 for today", self._call_count)

    def _do_get(self, endpoint: str, params: dict | None = None) -> dict | list | None:
        """Synchronous HTTP GET (called via asyncio.to_thread)."""
        self._check_rate_limit()

        url = f"{BASE_URL}/{endpoint}"
        all_params = {"apikey": self.api_key}
        if params:
            all_params.update(params)

        resp = httpx.get(url, params=all_params, timeout=30)
        self._call_count += 1
        logger.debug("FMP [%d/250] GET %s → %d", self._call_count, endpoint, resp.status_code)

        if resp.status_code != 200:
            logger.error("FMP API error %d: %s", resp.status_code, resp.text[:200])
            return None

        data = resp.json()

        # FMP returns {"Error Message": "..."} on bad requests
        if isinstance(data, dict) and "Error Message" in data:
            logger.error("FMP error: %s", data["Error Message"])
            return None

        return data

    async def get_earnings_transcript(
        self, ticker: str, year: int, quarter: int
    ) -> dict | None:
        """Fetch an earnings call transcript for a specific quarter.

        Returns dict with keys: symbol, quarter, year, date, content.
        """
        data = await asyncio.to_thread(
            self._do_get,
            "earning-call-transcript",
            {"symbol": ticker, "year": year, "quarter": quarter},
        )
        if not data:
            return None
        if isinstance(data, list):
            return data[0] if data else None
        return data

    async def get_earnings_calendar(self, ticker: str) -> list[dict]:
        """Fetch earnings history with actuals AND estimates.

        Replaces the old earnings-surprises endpoint. Returns list of dicts:
        date, symbol, epsActual, epsEstimated, revenueActual, revenueEstimated.
        Future-dated rows have null actuals.
        """
        data = await asyncio.to_thread(
            self._do_get,
            "earnings",
            {"symbol": ticker},
        )
        return data if isinstance(data, list) else []

    async def get_analyst_estimates(
        self, ticker: str, period: str = "annual"
    ) -> list[dict]:
        """Fetch consensus analyst estimates.

        Free tier supports period="annual" only. Quarterly is premium.
        Returns list of dicts with: date, symbol, revenueAvg, epsAvg, etc.
        """
        data = await asyncio.to_thread(
            self._do_get,
            "analyst-estimates",
            {"symbol": ticker, "period": period},
        )
        return data if isinstance(data, list) else []

    async def get_income_statement(
        self, ticker: str, period: str = "quarter", limit: int = 20
    ) -> list[dict]:
        """Fetch quarterly (or annual) income statements."""
        data = await asyncio.to_thread(
            self._do_get,
            "income-statement",
            {"symbol": ticker, "period": period, "limit": limit},
        )
        return data if isinstance(data, list) else []

    async def get_cash_flow_statement(
        self, ticker: str, period: str = "quarter", limit: int = 20
    ) -> list[dict]:
        """Fetch quarterly (or annual) cash flow statements."""
        data = await asyncio.to_thread(
            self._do_get,
            "cash-flow-statement",
            {"symbol": ticker, "period": period, "limit": limit},
        )
        return data if isinstance(data, list) else []

    async def get_balance_sheet_statement(
        self, ticker: str, period: str = "quarter", limit: int = 20
    ) -> list[dict]:
        """Fetch quarterly (or annual) balance sheet statements."""
        data = await asyncio.to_thread(
            self._do_get,
            "balance-sheet-statement",
            {"symbol": ticker, "period": period, "limit": limit},
        )
        return data if isinstance(data, list) else []


# Singleton instance (lazy — only usable when fmp_api_key is set)
_client: FMPClient | None = None


def get_fmp_client() -> FMPClient | None:
    """Get the FMP client singleton, or None if no API key is configured."""
    global _client
    if not settings.fmp_api_key:
        return None
    if _client is None:
        _client = FMPClient()
    return _client
