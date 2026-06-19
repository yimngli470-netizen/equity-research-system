"""IR scraper main entry — fetch a transcript for a specific quarter.

Orchestrates: registry lookup → discovery → optional LLM repair → extract.
"""

import logging
from dataclasses import dataclass

from app.ingestion.ir import discovery, extract, registry, repair

logger = logging.getLogger(__name__)

# Many IR sites (Micron, others) silently drop responses to non-browser UAs.
# A standard Chrome UA gets us past those WAF rules. Volume here is tiny
# (a handful of requests per ticker per quarter), so this is not abusive.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


@dataclass
class IRFetchResult:
    success: bool
    content: str | None
    source_url: str | None
    source_kind: str | None  # "ir_pdf" | "ir_html" | "ir_pptx"
    artifact_type: str | None  # "transcript" | "press_release" | "slides"
    has_qa: bool
    error: str | None = None


_QA_MARKERS = (
    "question-and-answer",
    "q&a session",
    "first question",
    "we will now begin the question",
)


def _detect_qa(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in _QA_MARKERS)


async def _download(url: str) -> tuple[bytes, str]:
    """Download the transcript/release. Browser-TLS-impersonating fetch first — the doc usually lives
    on the same WAF-protected IR domain that resets plain httpx (and headless Chromium). curl_cffi gets
    PDFs and HTML alike; a headless render is the last resort for JS-gated documents."""
    from app.ingestion.ir.browser_fetch import fetch_impersonated

    result = await fetch_impersonated(url, timeout=30)
    if result is not None:
        return result

    logger.info("[ir] impersonated download failed for %s — trying headless render", url)
    from app.ingestion.ir.render import fetch_rendered
    html = await fetch_rendered(url, _USER_AGENT)
    if html is None:
        raise RuntimeError("download failed (impersonated + rendered)")
    return html, "text/html"


async def fetch_transcript_from_ir(
    ticker: str, year: int, quarter: int
) -> IRFetchResult:
    """Try to fetch a transcript/release for (ticker, year, quarter) from the IR site.

    Returns IRFetchResult.success=False (with error) if:
      - No registry entry for the ticker
      - Programmatic discovery returns nothing AND repair also fails
      - Download or extraction fails
    """
    source = registry.get_source(ticker)
    if source is None:
        return IRFetchResult(
            success=False, content=None, source_url=None,
            source_kind=None, artifact_type=None, has_qa=False,
            error="no IR registry entry",
        )

    url, page_html = await discovery.discover_transcript_url(
        source, year, quarter, _USER_AGENT
    )

    if url is None and page_html is not None:
        # Programmatic discovery failed but we have the landing page. Try LLM repair.
        logger.info("Discovery failed for %s Q%d %d — trying LLM repair", ticker, quarter, year)
        repaired_url, new_strategy = await repair.repair_discovery(
            source, year, quarter, page_html
        )
        if repaired_url:
            url = repaired_url
            if new_strategy:
                registry.update_strategy(ticker, new_strategy)

    if url is None:
        return IRFetchResult(
            success=False, content=None, source_url=None,
            source_kind=None, artifact_type=source.artifact_type, has_qa=False,
            error="discovery + repair both failed",
        )

    try:
        content_bytes, content_type = await _download(url)
    except Exception as e:
        logger.exception("Failed to download %s for %s Q%d %d", url, ticker, quarter, year)
        return IRFetchResult(
            success=False, content=None, source_url=url,
            source_kind=None, artifact_type=source.artifact_type, has_qa=False,
            error=f"download failed: {e}",
        )

    try:
        text, source_kind = extract.extract_text(content_bytes, content_type, url)
    except Exception as e:
        logger.exception("Failed to extract %s for %s Q%d %d", url, ticker, quarter, year)
        return IRFetchResult(
            success=False, content=None, source_url=url,
            source_kind=None, artifact_type=source.artifact_type, has_qa=False,
            error=f"extract failed: {e}",
        )

    has_qa = source.artifact_type == "transcript" and _detect_qa(text)

    return IRFetchResult(
        success=True, content=text, source_url=url,
        source_kind=source_kind, artifact_type=source.artifact_type,
        has_qa=has_qa,
    )
