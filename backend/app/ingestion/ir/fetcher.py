"""IR scraper main entry — fetch a transcript for a specific quarter.

Orchestrates: registry lookup → discovery → optional LLM repair → extract.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

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


# HTTP 200 does not mean earnings content: JS-shell pages (ServiceNow), soft-404s (Microsoft),
# and IR landing pages (SpaceX) all extract to short nav boilerplate with near-zero financial
# vocabulary. Real releases run 15k+ chars with dozens of keyword hits (observed junk: ≤5k, ~0 hits).
_FIN_KEYWORDS = ("revenue", "income", "margin", "eps", "earnings per share")
_SOFT_ERROR_MARKERS = ("cannot be found", "page not found", "access denied", "page you requested")


def is_substantive_earnings_text(text: str) -> bool:
    """True if extracted text looks like a real earnings doc, not a nav shell / soft-404.

    Shared by the runtime content-check and autodiscover's validation so both apply the identical bar.
    """
    lower = text.lower()
    if any(m in lower for m in _SOFT_ERROR_MARKERS):
        return False
    keyword_hits = sum(lower.count(k) for k in _FIN_KEYWORDS)
    return len(text) >= 3000 and keyword_hits >= 5


# Back-compat alias for the private call sites in this module.
_is_substantive = is_substantive_earnings_text


_ATTACHMENT_RE = re.compile(r"""href=["']([^"']+\.pdf(?:\?[^"']*)?)["']""", re.I)
# Filename hints that mark the earnings document itself rather than a 10-Q, proxy, or ESG report
# that happens to sit on the same page.
_ATTACHMENT_HINTS = ("earnings", "results", "release", "transcript", "presentation")


def _find_attachment_url(html: bytes, base_url: str, year: int, quarter: int) -> str | None:
    """Best PDF attachment linked from an IR press-release page, or None.

    Many IR pages (Alphabet's q4cdn-backed site, most Q4 Inc. tenants) render the release body in
    JS but still emit the authoritative PDF as a plain <a href> in the static HTML. When HTML
    extraction comes back as a shell, that PDF is the real document — and fetching it is far
    cheaper and more reliable than a headless render, which WAFs frequently 403.
    """
    try:
        text = html.decode("utf-8", "replace")
    except Exception:
        return None

    best, best_score = None, -1
    for href in _ATTACHMENT_RE.findall(text):
        # Protocol-relative (//host/path) and site-relative hrefs both need resolving against base.
        absolute = urljoin(base_url, href)
        low = absolute.lower()
        score = sum(2 for h in _ATTACHMENT_HINTS if h in low)
        if str(year) in low:
            score += 2
        if f"q{quarter}" in low or f"{quarter}q" in low:
            score += 2
        if score > best_score:
            best, best_score = absolute, score

    # Require at least one positive signal — an unhinted PDF is as likely to be an ESG report.
    return best if best_score > 0 else None


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
    ticker: str, year: int, quarter: int, source: "registry.IRSource | None" = None
) -> IRFetchResult:
    """Try to fetch a transcript/release for (ticker, year, quarter) from the IR site.

    `source` defaults to the registry entry for the ticker; pass an in-memory IRSource to validate a
    candidate config WITHOUT persisting it (used by autodiscover before writing to sources.yaml).

    Returns IRFetchResult.success=False (with error) if:
      - No registry entry for the ticker
      - Programmatic discovery returns nothing AND repair also fails
      - Download or extraction fails
    """
    if source is None:
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

    # Held back until the repaired URL actually yields substantive content AND the proposed
    # strategy re-derives a link from this page. Persisting on the LLM's say-so (as this used to)
    # writes hallucinations into sources.yaml permanently — UBER Q2 2026 produced a perfectly
    # plausible ".../Uber-Q2-26-Earnings-Call-Transcript.pdf" that 404s.
    pending_strategy: registry.DiscoveryStrategy | None = None
    if url is None and page_html is not None:
        # Programmatic discovery failed but we have the landing page. Try LLM repair.
        logger.info("Discovery failed for %s Q%d %d — trying LLM repair", ticker, quarter, year)
        repaired_url, new_strategy = await repair.repair_discovery(
            source, year, quarter, page_html
        )
        if repaired_url:
            url = repaired_url
            pending_strategy = new_strategy

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

    # extract_text is CPU-bound (pdfplumber page loop / BeautifulSoup parse) and can run for
    # seconds on a large filing — off the event loop so it can't stall the whole API server.
    effective_url = url
    try:
        text, source_kind = await asyncio.to_thread(
            extract.extract_text, content_bytes, content_type, url
        )
    except Exception as e:
        logger.exception("Failed to extract %s for %s Q%d %d", url, ticker, quarter, year)
        return IRFetchResult(
            success=False, content=None, source_url=url,
            source_kind=None, artifact_type=source.artifact_type, has_qa=False,
            error=f"extract failed: {e}",
        )

    if source_kind == "ir_html" and not _is_substantive(text):
        # The static fetch returned a shell (JS-injected body) or a soft error page. Two recoveries,
        # cheapest first; otherwise refuse — storing boilerplate as a transcript poisons KPI
        # extraction downstream (and idempotency makes it sticky).
        logger.info("[ir] %s extracted only %d non-substantive chars from %s — trying attachment",
                    ticker, len(text), url)

        # (a) Follow the linked PDF. The body may be JS-gated, but the authoritative release PDF is
        #     usually a plain href in the same static HTML — and unlike a headless render, fetching
        #     it goes through the impersonated path that already got us this page.
        pdf_url = _find_attachment_url(content_bytes, url, year, quarter)
        if pdf_url:
            logger.info("[ir] %s following attachment %s", ticker, pdf_url)
            try:
                pdf_bytes, pdf_type = await _download(pdf_url)
                pdf_text, pdf_kind = await asyncio.to_thread(
                    extract.extract_text, pdf_bytes, pdf_type, pdf_url
                )
                if _is_substantive(pdf_text):
                    text, source_kind, effective_url = pdf_text, pdf_kind, pdf_url
                    logger.info("[ir] %s recovered %d chars from attachment", ticker, len(text))
            except Exception:
                logger.exception("[ir] %s attachment fetch failed for %s", ticker, pdf_url)

        # (b) Fall back to a headless render of the original page.
        if not _is_substantive(text):
            logger.info("[ir] %s no usable attachment — retrying rendered", ticker)
            from app.ingestion.ir.render import fetch_rendered
            html = await fetch_rendered(url, _USER_AGENT)
            if html is not None:
                try:
                    rendered_text, rendered_kind = await asyncio.to_thread(
                        extract.extract_text, html, "text/html", url
                    )
                    if _is_substantive(rendered_text):
                        text, source_kind = rendered_text, rendered_kind
                except Exception:
                    logger.exception("Failed to extract rendered %s for %s", url, ticker)

        if not _is_substantive(text):
            return IRFetchResult(
                success=False, content=None, source_url=url,
                source_kind=None, artifact_type=source.artifact_type, has_qa=False,
                error=f"content check failed: {len(text)} chars of non-financial text (shell or error page)",
            )

    has_qa = source.artifact_type == "transcript" and _detect_qa(text)

    # The repaired strategy has now earned persistence: its URL produced substantive content.
    # Second gate — it must also re-derive a link from this page. A strategy that can't reproduce
    # its own find is useless next run, and writing it would clobber a possibly-better existing
    # pattern. Verified here rather than at repair time so we only ever persist what actually paid
    # off end to end.
    if pending_strategy is not None:
        try:
            rederived = discovery._find_link(
                pending_strategy, page_html, source.ir_url, year, quarter
            )
        except Exception:
            rederived = None
        if rederived:
            registry.update_strategy(ticker, pending_strategy)
            logger.info("[ir] %s persisted repaired strategy %r (re-derives %s)",
                        ticker, pending_strategy.pattern, rederived)
        else:
            logger.info(
                "[ir] %s NOT persisting repaired strategy %r — content was good but the pattern "
                "re-derives nothing, so it would fail on the next run",
                ticker, pending_strategy.pattern,
            )

    return IRFetchResult(
        # effective_url, not url — when we followed an attachment the PDF is the real provenance.
        success=True, content=text, source_url=effective_url,
        source_kind=source_kind, artifact_type=source.artifact_type,
        has_qa=has_qa,
    )
