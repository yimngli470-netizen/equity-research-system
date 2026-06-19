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


async def _fetch(url: str, user_agent: str) -> tuple[bytes, str, bool]:
    """(content, content_type, was_rendered). Browser-TLS-impersonating fetch first — it's cheap and
    defeats the JA3/WAF fingerprint blocks that reset plain httpx AND headless Chromium (ISRG/UBER/FIG).
    Only if that fails do we fall back to a headless render (for sites whose links are JS-injected)."""
    from app.ingestion.ir.browser_fetch import fetch_impersonated

    result = await fetch_impersonated(url)
    if result is not None:
        content, content_type = result
        return content, content_type, False

    logger.info("[ir] impersonated fetch failed for %s — trying headless render", url)
    from app.ingestion.ir.render import fetch_rendered
    html = await fetch_rendered(url, user_agent)
    if html is None:
        raise RuntimeError("impersonated and rendered fetch both failed")
    return html, "text/html", True


def _find_link(strategy, content: bytes, landing_url: str, year: int, quarter: int) -> str | None:
    """Apply the configured link strategy to page bytes; absolute transcript/release URL or None."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(content, "html.parser")
    if strategy.type == "link_regex":
        pattern = re.compile(_interpolate(strategy.pattern, year, quarter), re.IGNORECASE)
        for a in soup.find_all("a", href=True):
            if pattern.search(a["href"]) or pattern.search(a.get_text(strip=True)):
                return urljoin(landing_url, a["href"])
        return None
    if strategy.type == "css_selector":
        el = soup.select_one(_interpolate(strategy.pattern, year, quarter))
        if el and el.get("href"):
            return urljoin(landing_url, el["href"])
        return None
    logger.warning("Unknown strategy type: %s", strategy.type)
    return None


async def discover_transcript_url(
    source: IRSource, year: int, quarter: int, user_agent: str
) -> tuple[str | None, bytes | None]:
    """Apply the configured strategy to find a transcript/release URL.

    Returns (url, ir_landing_html) — the second item is the raw IR page bytes (rendered if needed),
    passed back so repair.py can re-use it without a second fetch. url_template never fetches.
    """
    strategy = source.strategy

    if strategy.type == "url_template":
        return _interpolate(strategy.pattern, year, quarter), None

    landing_url = _interpolate(source.ir_url, year, quarter)
    try:
        content, _, was_rendered = await _fetch(landing_url, user_agent)
    except Exception:
        logger.exception("Failed to fetch IR landing page for %s: %s", source.ticker, landing_url)
        return None, None

    url = _find_link(strategy, content, landing_url, year, quarter)

    # Static page had no matching link — the links may be JS-injected. Render once and re-search.
    if url is None and not was_rendered:
        from app.ingestion.ir.render import fetch_rendered
        rendered = await fetch_rendered(landing_url, user_agent)
        if rendered:
            content = rendered
            url = _find_link(strategy, content, landing_url, year, quarter)

    return url, content
