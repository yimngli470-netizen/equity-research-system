"""Programmatic transcript-link discovery on IR landing pages.

Three strategy types are supported (see registry.DiscoveryStrategy):
  - link_regex   — find an <a> whose href or text matches the regex
  - css_selector — CSS selector returning the first matching <a> element
  - url_template — direct URL with {year}/{quarter} interpolation (no scrape)
"""

import logging
import re
from urllib.parse import urljoin

from app.ingestion.ir.registry import IRSource

logger = logging.getLogger(__name__)


_ORDINAL_BY_QUARTER = {1: "first", 2: "second", 3: "third", 4: "fourth"}


def _interpolate(template: str, year: int, quarter: int) -> str:
    return template.format(
        year=year,
        quarter=quarter,
        q=quarter,
        yr=year,
        ordinal=_ORDINAL_BY_QUARTER.get(quarter, str(quarter)),
    )


async def _fetch(url: str, user_agent: str) -> tuple[bytes, str]:
    import httpx

    headers = {"User-Agent": user_agent}
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "")


async def discover_transcript_url(
    source: IRSource, year: int, quarter: int, user_agent: str
) -> tuple[str | None, bytes | None]:
    """Apply the configured strategy to find a transcript/release URL.

    Returns (url, ir_landing_html) — the second item is the raw IR page bytes,
    passed back so repair.py can re-use it without a second fetch.
    For url_template strategies the landing page is never fetched (None).
    """
    strategy = source.strategy

    if strategy.type == "url_template":
        url = _interpolate(strategy.pattern, year, quarter)
        return url, None

    landing_url = _interpolate(source.ir_url, year, quarter)
    try:
        content, _ = await _fetch(landing_url, user_agent)
    except Exception:
        logger.exception("Failed to fetch IR landing page for %s: %s", source.ticker, landing_url)
        return None, None

    if strategy.type == "link_regex":
        pattern = re.compile(_interpolate(strategy.pattern, year, quarter), re.IGNORECASE)
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if pattern.search(href) or pattern.search(text):
                return urljoin(landing_url, href), content
        return None, content

    if strategy.type == "css_selector":
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "html.parser")
        selector = _interpolate(strategy.pattern, year, quarter)
        el = soup.select_one(selector)
        if el and el.get("href"):
            return urljoin(landing_url, el["href"]), content
        return None, content

    logger.warning("Unknown strategy type: %s", strategy.type)
    return None, content
