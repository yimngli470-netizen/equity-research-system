"""LLM-driven discovery fallback when programmatic discovery fails.

Asks Claude to find the right transcript link AND emit a replacement
strategy. The caller persists the new strategy via registry.update_strategy()
so the next run is back to programmatic (no LLM cost per run).
"""

import asyncio
import json
import logging

import anthropic

from app.config import settings
from app.ingestion.ir.registry import DiscoveryStrategy, IRSource

logger = logging.getLogger(__name__)

REPAIR_MODEL = settings.sonnet_model

_SYSTEM_PROMPT = """You are a web-scraping repair assistant. The user's pre-configured
strategy for finding an earnings transcript link on an investor-relations page has
failed. You will be given the raw HTML of the IR page and the target (year, quarter).

Find the URL of the most relevant earnings artifact for that quarter (transcript
preferred, then earnings press release, then slide deck). Also propose a new
generalized discovery strategy that would have found this link programmatically.

Reply with a single JSON object — no prose, no markdown fences:
{
  "found_url": "<absolute or relative URL, or null>",
  "artifact_type": "transcript" | "press_release" | "slides" | null,
  "new_strategy": {
    "type": "link_regex" | "css_selector" | "url_template",
    "pattern": "<the pattern; may use {year}, {quarter}, {q}, {yr} placeholders>"
  } | null,
  "confidence": "high" | "medium" | "low",
  "reasoning": "<one sentence on why this link / strategy>"
}

If you cannot find anything plausible, set found_url and new_strategy to null."""


def _call_claude(page_html: str, year: int, quarter: int, ticker: str) -> dict:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    user_prompt = (
        f"Ticker: {ticker}\n"
        f"Target: Q{quarter} {year}\n\n"
        f"IR page HTML (truncated to first 60k chars):\n```html\n{page_html[:60000]}\n```"
    )
    response = client.messages.create(
        model=REPAIR_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    content = response.content[0].text
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


async def repair_discovery(
    source: IRSource, year: int, quarter: int, page_html: bytes
) -> tuple[str | None, DiscoveryStrategy | None]:
    """Ask the LLM to find the link and propose a new strategy.

    Returns (found_url, new_strategy). Either may be None.
    Caller is responsible for persisting new_strategy via registry.update_strategy().
    """
    try:
        html_str = page_html.decode("utf-8", errors="replace")
        result = await asyncio.to_thread(_call_claude, html_str, year, quarter, source.ticker)
    except Exception:
        logger.exception("LLM repair failed for %s Q%d %d", source.ticker, quarter, year)
        return None, None

    found_url = result.get("found_url")
    strategy_raw = result.get("new_strategy")
    new_strategy = None
    if strategy_raw and strategy_raw.get("type") and strategy_raw.get("pattern"):
        new_strategy = DiscoveryStrategy(
            type=strategy_raw["type"], pattern=strategy_raw["pattern"]
        )

    logger.info(
        "Repair for %s Q%d %d: found_url=%s confidence=%s",
        source.ticker, quarter, year, found_url, result.get("confidence"),
    )
    return found_url, new_strategy
