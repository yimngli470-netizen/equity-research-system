"""Per-ticker KPI value extraction (roadmap 0.5).

For each metric defined in `ticker_key_metrics` (HBM revenue, DRAM ASP trend, inventory
days, ...), pull the period-specific VALUE from the latest earnings transcript / IR
materials, with a verbatim evidence quote and source. Results go to `ticker_kpi_values`,
so the earnings agent reports auditable numbers instead of guessing — and "not disclosed"
is a verified answer (we checked the text), not a silent gap.

LLM cost control: extraction runs once per (ticker, period); idempotent unless force=True.
"""

import asyncio
import json
import logging
from datetime import date

import anthropic
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm import make_llm_client
from app.models.financial import Financial
from app.models.key_metric import TickerKeyMetric, TickerKpiValue
from app.models.transcript import EarningsTranscript

logger = logging.getLogger(__name__)

MODEL = settings.sonnet_model
MAX_INPUT_CHARS = 120_000

SYSTEM_PROMPT = """You extract specific KPI values from an earnings call transcript / IR document.

You are given (1) a list of KPIs to find, each with a definition and target, and (2) the source
text. For EACH KPI, report the value found in the text for the most recent quarter.

CRITICAL RULES:
- Use ONLY the provided text. Do NOT infer, estimate, or pull from outside knowledge.
- If the KPI is not stated in the text, set value="not disclosed", evidence_quote=null,
  source="unknown". This is the correct answer when the data isn't there — do not guess.
- evidence_quote must be a VERBATIM span copied from the text that contains the value.
- Quote the number exactly as stated (units included).

Respond with valid JSON only, this exact schema:
{
  "kpis": [
    {
      "metric_name": "string — copy exactly from the input list",
      "value": "string — e.g. '$1.5B', '+39% QoQ', 'rising', 'not disclosed'",
      "vs_target": "beat | in_line | close | warning | miss | unknown",
      "trend": "up | down | flat | unknown",
      "evidence_quote": "string — verbatim text containing the value, or null"
    }
  ]
}"""


def _call(client: anthropic.Anthropic, ticker: str, defs_block: str, text: str) -> dict:
    user_prompt = (
        f"Extract these KPIs for {ticker} from the source text below.\n\n"
        f"KPIs TO FIND:\n{defs_block}\n\n"
        f"SOURCE TEXT:\n{text[:MAX_INPUT_CHARS]}\n\nRespond with JSON only."
    )
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=2048, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = resp.content[0].text
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        return json.loads(content.strip())
    except json.JSONDecodeError as e:
        logger.error("[kpi_extractor] JSON parse failed for %s: %s", ticker, e)
        return {"error": "json_parse_failed"}
    except anthropic.APIError as e:
        logger.error("[kpi_extractor] API error for %s: %s", ticker, e)
        return {"error": str(e)}


async def extract_kpis(db: AsyncSession, ticker: str, force: bool = False) -> int:
    """Extract defined-KPI values from the latest transcript. Returns rows upserted."""
    defs = (await db.execute(
        select(TickerKeyMetric).where(TickerKeyMetric.ticker == ticker)
        .order_by(TickerKeyMetric.priority.asc())
    )).scalars().all()
    if not defs:
        return 0

    tr = (await db.execute(
        select(EarningsTranscript).where(EarningsTranscript.ticker == ticker)
        .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc()).limit(1)
    )).scalar_one_or_none()
    if not tr or not tr.full_text:
        logger.info("[kpi_extractor] no transcript for %s — skipping", ticker)
        return 0

    period_end = (await db.execute(
        select(Financial.period_end_date).where(Financial.ticker == ticker)
        .order_by(Financial.period_end_date.desc()).limit(1)
    )).scalar_one_or_none() or date.today()

    if not force:
        existing = (await db.execute(
            select(TickerKpiValue.id).where(
                TickerKpiValue.ticker == ticker,
                TickerKpiValue.period_end_date == period_end,
            ).limit(1)
        )).scalar_one_or_none()
        if existing:
            logger.info("[kpi_extractor] %s already extracted for %s — skipping", ticker, period_end)
            return 0

    if not settings.anthropic_api_key:
        return 0

    defs_block = "\n".join(
        f"- {d.metric_name}: {d.definition}"
        + (f" | target: {d.target_or_threshold}" if d.target_or_threshold else "")
        + (f" | warning: {d.warning_threshold}" if d.warning_threshold else "")
        for d in defs
    )
    valid_names = {d.metric_name for d in defs}

    result = await asyncio.to_thread(_call, make_llm_client(),
                                     ticker, defs_block, tr.full_text)
    if "error" in result:
        return 0

    today = date.today()
    rows = []
    for k in result.get("kpis", []):
        name = k.get("metric_name")
        if name not in valid_names:
            continue
        value = (k.get("value") or "").strip() or "not disclosed"
        disclosed = value.lower() != "not disclosed"
        rows.append({
            "ticker": ticker,
            "period_end_date": period_end,
            "metric_name": name,
            "value": value[:200],
            "vs_target": k.get("vs_target") or "unknown",
            "trend": k.get("trend") or "unknown",
            "evidence_quote": (k.get("evidence_quote") or None) if disclosed else None,
            "source": (tr.source or "transcript") if disclosed else "unknown",
            "source_url": tr.source_url if disclosed else None,
            "as_of": today,
        })
    if not rows:
        return 0

    stmt = insert(TickerKpiValue).values(rows)
    cols = ("value", "vs_target", "trend", "evidence_quote", "source", "source_url", "as_of")
    stmt = stmt.on_conflict_do_update(
        constraint="uq_kpi_val_ticker_period_name",
        set_={c: getattr(stmt.excluded, c) for c in cols},
    )
    await db.execute(stmt)
    await db.commit()
    disclosed_n = sum(1 for r in rows if r["value"].lower() != "not disclosed")
    logger.info("[kpi_extractor] %s @ %s: %d KPIs (%d disclosed)", ticker, period_end, len(rows), disclosed_n)
    return len(rows)
