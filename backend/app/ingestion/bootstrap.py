"""Auto-bootstrap a newly-added ticker so it needs zero manual setup:

  1. Generate per-ticker KPI definitions (LLM, business-aware) -> ticker_key_metrics.
  2. Auto-discover the IR source (LLM proposes ir_url + artifact + pattern, validated by
     a reachability check) -> sources.yaml.

Both are idempotent (skip if already configured unless force). Outcomes are recorded in
ticker_onboarding (developer-facing, queryable) and surfaced as warnings to the UI when IR
auto-discovery can't be confirmed — distinguishing a likely-bad URL from an IP/WAF block,
so the developer knows whether to fix the URL or just run the pipeline from a residential IP.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import date

import anthropic
import httpx
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ingestion.ir import registry
from app.models.key_metric import TickerKeyMetric
from app.models.onboarding import DevTickerBootstrapStatus
from app.models.stock import Stock

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
_UA = "Mozilla/5.0 (research) equity-research-personal yimngli470@gmail.com"


@dataclass
class BootstrapResult:
    ticker: str
    kpi_status: str = "skipped"
    kpi_count: int = 0
    ir_status: str = "skipped"
    ir_url: str | None = None
    ir_artifact_type: str | None = None
    message: str | None = None
    warnings: list[str] = field(default_factory=list)  # user-facing


def _company_info(ticker: str, stock: Stock | None) -> dict:
    name = stock.name if stock else ticker
    sector = stock.sector if stock else None
    industry = stock.industry if stock else None
    summary = None
    try:
        info = yf.Ticker(ticker).info
        name = info.get("shortName") or info.get("longName") or name
        sector = sector or info.get("sector")
        industry = industry or info.get("industry")
        summary = info.get("longBusinessSummary")
    except Exception:
        pass
    return {"name": name, "sector": sector, "industry": industry,
            "summary": (summary or "")[:1500]}


def _llm_json(system: str, user: str) -> dict:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(model=MODEL, max_tokens=2048, system=system,
                                  messages=[{"role": "user", "content": user}])
    content = resp.content[0].text
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


# ── 1. KPI definitions ───────────────────────────────────────────────────────

_KPI_SYS = """You are an equity analyst. For the given company, output the 4-6 KPIs that most
matter for evaluating its QUARTERLY results — the specific metrics a specialist analyst tracks
for THIS business (not generic revenue/EPS). E.g. memory semis: HBM revenue, DRAM ASP, bit
growth, inventory days; ride-hailing: gross bookings, take rate, MAPCs; cloud: segment revenue
growth, RPO, margins.

For each KPI give: metric_name (<=8 words), definition, why_it_matters, target_or_threshold
(the bull case), warning_threshold (the bear red line), priority (1=most important).

Respond with JSON only: {"kpis":[{"metric_name","definition","why_it_matters",
"target_or_threshold","warning_threshold","priority"}]}"""


def _gen_kpis(ticker: str, info: dict) -> list[dict]:
    user = (f"Company: {info['name']} ({ticker}). Sector: {info['sector']}. "
            f"Industry: {info['industry']}.\nBusiness: {info['summary']}\n\nJSON only.")
    return _llm_json(_KPI_SYS, user).get("kpis", [])


async def generate_kpi_definitions(db: AsyncSession, ticker: str, info: dict, force: bool) -> tuple[str, int]:
    existing = (await db.execute(
        select(TickerKeyMetric.id).where(TickerKeyMetric.ticker == ticker).limit(1)
    )).scalar_one_or_none()
    if existing and not force:
        n = (await db.execute(
            select(TickerKeyMetric).where(TickerKeyMetric.ticker == ticker)
        )).scalars().all()
        return "skipped", len(n)
    if not settings.anthropic_api_key:
        return "failed", 0
    try:
        kpis = await asyncio.to_thread(_gen_kpis, ticker, info)
    except Exception as e:
        logger.exception("[bootstrap] KPI generation failed for %s", ticker)
        return "failed", 0
    if not kpis:
        return "failed", 0
    rows = [{
        "ticker": ticker,
        "metric_name": (k.get("metric_name") or "")[:120],
        "definition": k.get("definition") or "",
        "why_it_matters": k.get("why_it_matters"),
        "target_or_threshold": (k.get("target_or_threshold") or None) and str(k["target_or_threshold"])[:200],
        "warning_threshold": (k.get("warning_threshold") or None) and str(k["warning_threshold"])[:300],
        "priority": int(k.get("priority") or 3),
    } for k in kpis if k.get("metric_name")]
    stmt = insert(TickerKeyMetric).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_key_metric_ticker_name",
        set_={c: getattr(stmt.excluded, c) for c in
              ("definition", "why_it_matters", "target_or_threshold", "warning_threshold", "priority")},
    )
    await db.execute(stmt)
    await db.commit()
    return "ok", len(rows)


# ── 2. IR source auto-discovery ───────────────────────────────────────────────

_IR_SYS = """Identify a public company's official Investor Relations EARNINGS page and how its
per-quarter earnings artifacts are named. Prefer the RICHEST artifact (full call transcript or
slide deck) over a press release.

Respond with JSON only:
{"ir_url":"https://... official IR earnings/quarterly page",
 "artifact_type":"transcript|prepared_remarks|slides|press_release",
 "strategy":{"type":"link_regex|css_selector|url_template","pattern":"..."},
 "notes":"how artifacts are named / where they live"}

Use the real official IR domain (e.g. investor.<company>.com). link_regex matches a link's href
or text (case-insensitive); placeholders {year} {quarter} {q} {ordinal} are interpolated. If
unsure of the exact pattern, give a broad link_regex for earnings/transcript/results links."""


def _classify_url(url: str) -> tuple[str, str]:
    """Return (status, detail). status in ok|unreachable|not_found."""
    try:
        r = httpx.get(url, headers={"User-Agent": _UA}, follow_redirects=True, timeout=12)
        if r.status_code == 200:
            return "ok", f"reachable (HTTP 200, {len(r.text)} chars)"
        if r.status_code in (401, 403, 429):
            return "unreachable", f"HTTP {r.status_code} (WAF/IP block — URL may be correct)"
        if r.status_code == 404:
            return "not_found", "HTTP 404 (URL path likely wrong)"
        return "unreachable", f"HTTP {r.status_code}"
    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout):
        return "unreachable", "timeout (likely IP/WAF block — URL may be correct)"
    except httpx.ConnectError as e:
        return "not_found", f"connection failed ({e!r}) — domain may be wrong"
    except Exception as e:  # noqa: BLE001
        return "unreachable", f"fetch error: {e!r}"


def _propose_ir(ticker: str, info: dict) -> dict:
    return _llm_json(_IR_SYS, f"Company: {info['name']} ({ticker}). JSON only.")


async def discover_ir_source(ticker: str, info: dict, force: bool) -> tuple[str, str | None, str | None, str]:
    """Returns (status, ir_url, artifact_type, message)."""
    if registry.get_source(ticker) and not force:
        return "skipped", None, None, "IR source already configured."
    if not settings.anthropic_api_key:
        return "failed", None, None, "No API key for IR auto-discovery."
    try:
        prop = await asyncio.to_thread(_propose_ir, ticker, info)
    except Exception as e:
        logger.exception("[bootstrap] IR discovery LLM failed for %s", ticker)
        return "failed", None, None, f"Could not propose an IR source ({e!r}). Set sources.yaml manually."

    url = prop.get("ir_url")
    artifact = prop.get("artifact_type", "press_release")
    strat = prop.get("strategy") or {}
    if not url or not strat.get("type") or not strat.get("pattern"):
        return "failed", url, artifact, "LLM returned an incomplete IR config. Set sources.yaml manually."

    url_status, detail = await asyncio.to_thread(_classify_url, url)

    # Write the entry when reachable OR likely-blocked (so it works from a residential IP);
    # skip writing only when the URL looks wrong (not_found).
    if url_status in ("ok", "unreachable"):
        src = registry.IRSource(
            ticker=ticker.upper(), ir_url=url,
            strategy=registry.DiscoveryStrategy(type=strat["type"], pattern=strat["pattern"]),
            artifact_type=artifact,
            notes=(prop.get("notes") or "") + f"\n[auto-discovered {date.today()}; url check: {detail}]",
        )
        await asyncio.to_thread(registry.add_source, src, force)

    if url_status == "ok":
        return "ok", url, artifact, f"Auto-discovered IR source: {url} ({detail})."
    if url_status == "unreachable":
        return ("unreachable", url, artifact,
                f"Proposed IR URL {url} not reachable from this server: {detail}. "
                f"Written to sources.yaml — it should work when you run the pipeline from your "
                f"machine (residential IP). If it still fails there, verify the URL.")
    return ("not_found", url, artifact,
            f"Proposed IR URL {url} looks wrong: {detail}. NOT written — set the correct IR URL "
            f"in sources.yaml manually.")


# ── orchestration ─────────────────────────────────────────────────────────────

async def bootstrap_ticker(db: AsyncSession, ticker: str, force: bool = False) -> BootstrapResult:
    """Auto-generate KPI defs + discover IR source for a ticker. Idempotent unless force."""
    ticker = ticker.upper()
    res = BootstrapResult(ticker=ticker)

    # Fast path: fully configured already → no yfinance/LLM cost (runs every pipeline).
    if not force:
        has_kpis = (await db.execute(
            select(TickerKeyMetric.id).where(TickerKeyMetric.ticker == ticker).limit(1)
        )).scalar_one_or_none()
        if has_kpis and registry.get_source(ticker):
            res.kpi_status = res.ir_status = "skipped"
            return res

    stock = (await db.execute(select(Stock).where(Stock.ticker == ticker))).scalar_one_or_none()
    info = await asyncio.to_thread(_company_info, ticker, stock)

    res.kpi_status, res.kpi_count = await generate_kpi_definitions(db, ticker, info, force)
    res.ir_status, res.ir_url, res.ir_artifact_type, res.message = await discover_ir_source(ticker, info, force)

    # User-facing warnings
    if res.kpi_status == "failed":
        res.warnings.append(f"{ticker}: could not auto-generate KPI definitions.")
    if res.ir_status in ("unreachable", "not_found", "failed"):
        res.warnings.append(f"{ticker}: IR source auto-discovery — {res.message}")

    # Developer-facing record
    stmt = insert(DevTickerBootstrapStatus).values(
        ticker=ticker, kpi_status=res.kpi_status, kpi_count=res.kpi_count,
        ir_status=res.ir_status, ir_url=res.ir_url, ir_artifact_type=res.ir_artifact_type,
        message=res.message,
    ).on_conflict_do_update(
        constraint="uq_dev_bootstrap_ticker",
        set_={"kpi_status": res.kpi_status, "kpi_count": res.kpi_count, "ir_status": res.ir_status,
              "ir_url": res.ir_url, "ir_artifact_type": res.ir_artifact_type, "message": res.message},
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("[bootstrap] %s: kpi=%s(%d) ir=%s", ticker, res.kpi_status, res.kpi_count, res.ir_status)
    # Also log failures at WARNING so they surface in `docker compose logs backend`
    # (the dev_ticker_bootstrap_status table is the durable copy, since Docker logs are
    # lost on `docker compose down`).
    if res.ir_status in ("unreachable", "not_found", "failed") or res.kpi_status == "failed":
        logger.warning("[bootstrap] %s needs attention — kpi=%s ir=%s :: %s",
                       ticker, res.kpi_status, res.ir_status, res.message)
    return res
