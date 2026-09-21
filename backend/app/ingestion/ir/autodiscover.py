"""Earnings-page auto-discovery from a user-pasted IR URL.

The problem this solves: when adding a ticker, the user usually pastes the IR *overview* page
(e.g. servicenow.com/company/investor-relations.html), not the actual earnings-release listing one
or two clicks deeper. A fixed broad regex on the overview page then either finds nothing or latches
onto the wrong link (an earnings-call *event* page full of webcast boilerplate) — which gets stored
as a "transcript" and poisons KPI extraction downstream.

Why this is safe where the OLD auto-discovery (removed) was not: that one asked an LLM to *invent*
an IR domain from the company name, and it guessed non-obvious hosts wrong (ISRG → isrg.intuitive.com).
Here we never invent URLs — we start from a real page the user gave us, crawl only links that actually
exist on the company's own IR site, let the LLM *pick* from that harvested inventory, and then PROVE
the choice by running the full runtime path (discovery → download → extract → substance check) before
persisting anything. A wrong pick fails validation and is never written.

Flow (one-time per ticker, ~2-6 page fetches on the IR site + 1 Sonnet call):
  1. Fetch the seed page (curl_cffi → headless render). Harvest all <a> links.
  2. Follow up to a few high-scoring "index" links one level deep (quarterly results / press
     releases / financials), harvesting their links too — this is where GLW/VRT hide the real docs.
  3. Ask Sonnet to pick, from the combined inventory, the index page + a reusable discovery strategy
     (link_regex/url_template with {year}/{q}/{ordinal} placeholders) + the latest period it can see.
  4. Validate that strategy end-to-end for that latest period. Accept only on a substantive result.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from app.config import settings
from app.ingestion.ir import fetcher, registry
from app.ingestion.ir.browser_fetch import fetch_impersonated
from app.ingestion.ir.render import fetch_rendered
from app.llm import make_llm_client

logger = logging.getLogger(__name__)

MODEL = settings.sonnet_model

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Anchor text / URL substrings that mark a page likely to *list* earnings docs. Used to rank which
# links to follow one level deep — not to pick the final doc (the LLM does that).
_INDEX_HINTS = (
    "quarterly result", "quarterly-result", "press release", "press-release",
    "earnings", "financial result", "financial-result", "news and events",
    "news-and-events", "news & events", "financials", "news-release", "news release",
    "events and presentations", "results", "reports",
)

_MAX_INDEX_PAGES = 4       # candidate index pages to crawl one level deep
_MAX_LINKS_TO_LLM = 160    # cap on harvested links handed to the LLM (keeps the prompt cheap)


@dataclass
class DiscoveryResult:
    status: str                       # "ok" | "needs_attention"
    ir_url: str | None = None         # index page the runtime should crawl
    strategy_type: str | None = None
    strategy_pattern: str | None = None
    artifact_type: str | None = None
    sample_url: str | None = None     # the concrete doc validation actually fetched
    sample_chars: int = 0
    confidence: str | None = None
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "ir_url": self.ir_url,
            "strategy_type": self.strategy_type,
            "strategy_pattern": self.strategy_pattern,
            "artifact_type": self.artifact_type,
            "sample_url": self.sample_url,
            "sample_chars": self.sample_chars,
            "confidence": self.confidence,
            "message": self.message,
        }


async def _fetch_html(url: str) -> str | None:
    """curl_cffi first (defeats JA3/WAF), headless render as fallback (JS-injected links). HTML str or None."""
    result = await fetch_impersonated(url, timeout=25)
    html = result[0] if result else None
    if html is None:
        html = await fetch_rendered(url, _USER_AGENT, timeout=45)
    if html is None:
        return None
    text = html.decode("utf-8", "ignore")
    # Many IR listings inject their doc links via JS; if a static fetch returned few links, re-render.
    if result is not None and text.count("<a ") < 25:
        rendered = await fetch_rendered(url, _USER_AGENT, timeout=45)
        if rendered:
            text = rendered.decode("utf-8", "ignore")
    return text


def _harvest_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return [(absolute_url, anchor_text)] from a page, deduped, same-site + PDF links only."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if not href.startswith("http"):
            continue
        host = urlparse(href).netloc
        # Keep same-registrable-domain links (IR sites span investor.x.com / newsroom.x.com / q4cdn CDNs).
        cdn = "q4cdn.com" in host or href.lower().endswith(".pdf")
        if not cdn and base_host.split(".")[-2:] != host.split(".")[-2:]:
            continue
        if href in seen:
            continue
        seen.add(href)
        text = a.get_text(" ", strip=True)[:120]
        out.append((href, text))
    return out


def _looks_like_index(url: str, text: str) -> bool:
    blob = (url + " " + text).lower()
    return any(h in blob for h in _INDEX_HINTS)


async def _build_inventory(seed_url: str) -> list[tuple[str, str]]:
    """Crawl seed + a few index pages one level deep; return the combined harvested link inventory."""
    seed_html = await _fetch_html(seed_url)
    if seed_html is None:
        return []
    inventory = _harvest_links(seed_html, seed_url)

    # Rank index-looking links on the seed page, follow the top few, harvest their links too.
    index_candidates = [(u, t) for (u, t) in inventory if _looks_like_index(u, t) and u != seed_url]
    # Prefer listing pages over single-article pages: shorter path depth first.
    index_candidates.sort(key=lambda ut: (ut[0].count("/"), len(ut[0])))
    followed = 0
    for url, _text in index_candidates:
        if followed >= _MAX_INDEX_PAGES:
            break
        followed += 1
        sub_html = await _fetch_html(url)
        if sub_html:
            inventory.extend(_harvest_links(sub_html, url))

    # Dedup while preserving order; cap for the LLM prompt.
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for u, t in inventory:
        if u not in seen:
            seen.add(u)
            deduped.append((u, t))
    return deduped[:_MAX_LINKS_TO_LLM]


_SYSTEM_PROMPT = """You configure an earnings-transcript scraper. Given a harvested list of links
from a company's Investor Relations site, identify how to reach its QUARTERLY EARNINGS RELEASES
(the press release / transcript with revenue, EPS, and margin figures) — NOT the earnings-call
event/webcast registration page, NOT the annual report, NOT SEC filings.

Return a single JSON object, no prose, no markdown fences:
{
  "ir_url": "<the LISTING/index page to crawl each quarter (where release links appear), absolute>",
  "strategy": {
    "type": "link_regex" | "url_template",
    "pattern": "<regex matching the release link's href/text, OR a direct URL template>"
  },
  "artifact_type": "transcript" | "press_release" | "slides",
  "sample_url": "<the absolute URL of the single most recent earnings release you can see>",
  "latest_year": <calendar year of that most recent release, integer>,
  "latest_quarter": <1-4, the fiscal quarter of that release>,
  "confidence": "high" | "medium" | "low",
  "reasoning": "<one sentence>"
}

Rules for `pattern` — it must generalize to FUTURE quarters, so use placeholders:
  {year} = 4-digit year, {q} = quarter number 1-4, {ordinal} = first|second|third|fourth.
- link_regex matches an <a> href OR its text (case-insensitive). Example that matches
  "Corning-Announces-Strong-First-Quarter-2026-Financial-Results":
  "Announces.*{ordinal}-Quarter-{year}.*Financial-Results"
- Require a "reports/announces/results" style word so pre-announcement ("to Announce ... on <date>")
  pages never match.
- Prefer a link_regex on a listing page over url_template unless the site uses stable, predictable
  URLs. If you truly cannot find earnings releases in these links, set ir_url and strategy to null."""


def _call_llm(ticker: str, name: str, seed_url: str, inventory: list[tuple[str, str]]) -> dict:
    links_block = "\n".join(f"- {url}  ::  {text}" for url, text in inventory)
    user = (
        f"Ticker: {ticker} ({name})\n"
        f"User-pasted IR page: {seed_url}\n\n"
        f"Harvested links (url :: anchor text):\n{links_block}\n\nJSON only."
    )
    client = make_llm_client()
    resp = client.messages.create(
        model=MODEL, max_tokens=1024, system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    content = resp.content[0].text
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


async def discover_earnings_source(
    ticker: str, seed_url: str, name: str | None = None
) -> DiscoveryResult:
    """Crawl from `seed_url`, LLM-pick an earnings strategy, validate it end-to-end.

    On success the returned strategy is proven (a real, substantive earnings doc was fetched through
    the exact runtime path). Does NOT persist — the caller decides when to write to the registry.
    """
    ticker = ticker.upper()
    name = name or ticker

    if not settings.llm_configured:
        return DiscoveryResult(status="needs_attention",
                               message="LLM not configured — cannot auto-discover the earnings page.")

    inventory = await _build_inventory(seed_url)
    if not inventory:
        return DiscoveryResult(
            status="needs_attention",
            message=f"Could not reach or read {seed_url} (site blocked the fetch or has no links). "
                    "Paste the page that lists quarterly earnings releases.",
        )

    try:
        pick = await asyncio.to_thread(_call_llm, ticker, name, seed_url, inventory)
    except Exception:
        logger.exception("[autodiscover] LLM pick failed for %s", ticker)
        return DiscoveryResult(status="needs_attention",
                               message="Auto-discovery hit an error analyzing the IR page. Try again, "
                                       "or paste the quarterly-results listing page directly.")

    ir_url = pick.get("ir_url")
    strat = pick.get("strategy") or {}
    if not ir_url or not strat.get("type") or not strat.get("pattern"):
        return DiscoveryResult(
            status="needs_attention",
            confidence=pick.get("confidence"),
            message="Couldn't identify a quarterly earnings-release page from that URL. "
                    "Paste the page that lists earnings press releases (e.g. 'Quarterly Results').",
        )

    candidate = registry.IRSource(
        ticker=ticker,
        ir_url=ir_url,
        strategy=registry.DiscoveryStrategy(type=strat["type"], pattern=strat["pattern"]),
        artifact_type=pick.get("artifact_type") or "press_release",
    )

    # Validate the STRATEGY (not just the sample URL) for the period the LLM claims it can see, by
    # running the full runtime path incl. the substance check. This is what makes a wrong pick fail
    # closed instead of getting stored as a junk transcript.
    year = pick.get("latest_year")
    quarter = pick.get("latest_quarter")
    if not isinstance(year, int) or quarter not in (1, 2, 3, 4):
        return DiscoveryResult(
            status="needs_attention", ir_url=ir_url,
            strategy_type=strat["type"], strategy_pattern=strat["pattern"],
            confidence=pick.get("confidence"),
            message="Found a likely earnings page but couldn't determine the latest quarter to verify it. "
                    "Adding with this config; check the next earnings run.",
        )

    result = await fetcher.fetch_transcript_from_ir(ticker, year, quarter, source=candidate)
    if result.success and result.content and fetcher.is_substantive_earnings_text(result.content):
        return DiscoveryResult(
            status="ok", ir_url=ir_url,
            strategy_type=strat["type"], strategy_pattern=strat["pattern"],
            artifact_type=candidate.artifact_type,
            sample_url=result.source_url, sample_chars=len(result.content),
            confidence=pick.get("confidence"),
            message=f"Found the earnings page — verified against Q{quarter} {year} "
                    f"({len(result.content):,} chars of real financials).",
        )

    logger.info("[autodiscover] %s validation failed: %s", ticker, result.error)
    return DiscoveryResult(
        status="needs_attention", ir_url=ir_url,
        strategy_type=strat["type"], strategy_pattern=strat["pattern"],
        confidence=pick.get("confidence"),
        message="Found a candidate earnings page but couldn't verify a real release from it "
                f"(Q{quarter} {year}: {result.error or 'no substantive content'}). "
                "It may still work at the next earnings date, or paste the exact releases page.",
    )


async def discover_and_register(
    ticker: str, seed_url: str, name: str | None = None
) -> DiscoveryResult:
    """Run discovery and, only on a validated hit, persist the strategy to sources.yaml (overwrite)."""
    res = await discover_earnings_source(ticker, seed_url, name)
    if res.status == "ok":
        from datetime import date

        registry.add_source(
            registry.IRSource(
                ticker=ticker.upper(),
                ir_url=res.ir_url,
                strategy=registry.DiscoveryStrategy(type=res.strategy_type, pattern=res.strategy_pattern),
                artifact_type=res.artifact_type or "press_release",
                notes=f"Auto-discovered from {seed_url} ({date.today()}); "
                      f"verified {res.sample_chars} chars.",
            ),
            overwrite=True,
        )
        logger.info("[autodiscover] %s registered: ir_url=%s strategy=%s/%s",
                    ticker, res.ir_url, res.strategy_type, res.strategy_pattern)
    return res
