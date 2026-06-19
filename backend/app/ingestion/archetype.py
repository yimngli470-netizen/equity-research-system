"""Archetype classification (roadmap 1.1) — assign each stock a business-model archetype.

The label is an LLM judgment (it needs world knowledge: that MU is memory-cyclical, that META is
a platform), but it is **grounded** on a measured quant profile (revenue cyclicality, margin
level/stability, capex intensity) computed from the EDGAR spine — not guessed from the ticker. We
store the label, the numbers it was grounded on, and a short rationale, so the classification is
auditable and re-runnable.

Why LLM and not a trained classifier here: at N≈15 names and 6 coarse buckets there's no training
set, and the LLM brings knowledge a classifier can't. Unsupervised clustering (ML M2) will later
*validate* whether these 6 buckets are the right ones.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm import make_llm_client
from app.ingestion.bootstrap import _company_info  # reuse name/sector/industry/summary lookup
from app.measurement.profile import QuantProfile, compute_quant_profile
from app.models.stock import Stock

logger = logging.getLogger(__name__)

MODEL = settings.sonnet_model

# The 6 archetypes. Keep in sync with the roadmap; the classifier must return exactly one.
ARCHETYPES = (
    "cyclical-commodity",
    "secular-grower",
    "platform",
    "mature-compounder",
    "financial",
    "deep-value-turnaround",
)

_SYS = """You are an equity strategist. Assign the company to exactly ONE business-model archetype.
You are given a MEASURED quant profile from its SEC filings — ground your call on those numbers,
not on vibes. Use your knowledge of the business to break ties the numbers can't.

Archetypes (pick one):
- cyclical-commodity: demand/pricing swing with a cycle; high revenue-growth volatility, deep
  peak-to-trough revenue drawdowns, margins that expand and collapse. Commodity/price-taker
  economics (memory, DRAM/NAND, energy, materials, base chemicals, shipping). e.g. Micron.
- secular-grower: durable above-market growth from a structural tailwind; high average revenue
  growth, still scaling, margins often expanding but not yet mature. e.g. a category leader
  still early in adoption.
- platform: network-effect / aggregator economics; asset-light, high and STABLE gross margins,
  scale moat. e.g. Meta, Google, Visa.
- mature-compounder: steady mid-single to low-double-digit growth, high and stable margins,
  shallow drawdowns, returns capital. e.g. Apple, Microsoft, large staples.
- financial: bank / insurer / capital-markets; balance-sheet-driven economics where the standard
  margin/cyclicality reads don't apply the same way. Classify on the business, not the margins.
- deep-value-turnaround: depressed or negative margins, declining/erratic revenue, loss quarters;
  the thesis is recovery/restructuring, not growth.

Respond with JSON only:
{"archetype":"<one of the list>",
 "rationale":"<=2 sentences citing the specific numbers that drove the call",
 "confidence":"high|medium|low"}"""


@dataclass
class ArchetypeResult:
    ticker: str
    status: str                     # ok | skipped | insufficient_data | failed
    archetype: str | None = None
    confidence: str | None = None
    rationale: str | None = None
    profile: dict | None = None


def _profile_lines(p: QuantProfile) -> str:
    """Render the profile as labelled numbers for the prompt (percent where natural)."""
    def pct(x: float | None) -> str:
        return f"{x * 100:.1f}%" if x is not None else "n/a"

    return "\n".join([
        f"- history: {p.n_quarters} quarters",
        f"- TTM revenue growth (YoY): mean {pct(p.revenue_growth_mean)}, "
        f"volatility(std) {pct(p.revenue_growth_std)}, worst {pct(p.revenue_growth_min)}",
        f"- peak-to-trough TTM revenue drawdown: {pct(p.revenue_max_drawdown)}",
        f"- gross margin: mean {pct(p.gross_margin_mean)}, stability(std) {pct(p.gross_margin_std)}",
        f"- operating margin: mean {pct(p.operating_margin_mean)}, "
        f"stability(std) {pct(p.operating_margin_std)}",
        f"- net margin (mean): {pct(p.net_margin_mean)}",
        f"- loss quarters: {pct(p.loss_quarter_pct)}",
        f"- capex intensity (capex/revenue, TTM): {pct(p.capex_intensity_mean)}",
    ])


def _classify(info: dict, profile: QuantProfile) -> dict:
    client = make_llm_client()
    user = (
        f"Company: {info['name']} ({info.get('ticker','')}). Sector: {info['sector']}. "
        f"Industry: {info['industry']}.\n"
        f"Business: {info['summary']}\n\n"
        f"MEASURED quant profile (from SEC filings):\n{_profile_lines(profile)}\n\nJSON only."
    )
    resp = client.messages.create(model=MODEL, max_tokens=512, system=_SYS,
                                  messages=[{"role": "user", "content": user}])
    content = resp.content[0].text
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


async def classify_archetype(db: AsyncSession, ticker: str, force: bool = False) -> ArchetypeResult:
    """Classify (or re-classify) a ticker's archetype. Idempotent: skips if already set unless force."""
    ticker = ticker.upper()
    stock = await db.get(Stock, ticker)
    if stock is None:
        return ArchetypeResult(ticker, status="failed")

    if stock.archetype and not force:
        return ArchetypeResult(ticker, status="skipped", archetype=stock.archetype,
                               rationale=stock.archetype_rationale, profile=stock.archetype_features)

    profile = await compute_quant_profile(db, ticker)
    if profile is None:
        logger.info("[archetype] %s: insufficient financial history to classify", ticker)
        return ArchetypeResult(ticker, status="insufficient_data")

    if not settings.anthropic_api_key:
        return ArchetypeResult(ticker, status="failed", profile=profile.to_dict())

    info = await asyncio.to_thread(_company_info, ticker, stock)
    info["ticker"] = ticker
    try:
        out = await asyncio.to_thread(_classify, info, profile)
    except Exception:
        logger.exception("[archetype] classification failed for %s", ticker)
        return ArchetypeResult(ticker, status="failed", profile=profile.to_dict())

    archetype = str(out.get("archetype", "")).strip().lower()
    if archetype not in ARCHETYPES:
        logger.warning("[archetype] %s: LLM returned unknown archetype %r", ticker, archetype)
        return ArchetypeResult(ticker, status="failed", profile=profile.to_dict())

    rationale = (out.get("rationale") or "")[:1000]
    confidence = str(out.get("confidence", "")).strip().lower() or None

    await db.execute(
        update(Stock).where(Stock.ticker == ticker).values(
            archetype=archetype,
            archetype_source="llm",   # grounded-LLM label (upgrades any provisional "rules" label, 6.1)
            archetype_features=profile.to_dict(),
            archetype_rationale=rationale,
            archetype_as_of=date.today(),
        )
    )
    await db.commit()
    logger.info("[archetype] %s -> %s (%s)", ticker, archetype, confidence)
    return ArchetypeResult(ticker, status="ok", archetype=archetype, confidence=confidence,
                           rationale=rationale, profile=profile.to_dict())
