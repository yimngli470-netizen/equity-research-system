"""Forecast assumptions (roadmap 4.2) — the ONE new LLM call per ticker per quarter.

The LLM's job is exactly the judgment slice: read guidance LANGUAGE, weigh it against the
through-cycle anchors in the driver history, and emit assumption PATHS — every material assumption
tagged with its basis (guidance | trend | judgment). All numbers are FRACTIONS; code clamps and
compiles them (`model.py`). Smart-cached by input fingerprint, so it re-fires roughly once per
quarter (new filing/transcript/estimates), not per pipeline run.
"""

import asyncio
import json
import logging
from datetime import date

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.forecast.drivers import DriverHistory, format_drivers_for_llm
from app.models.estimate import AnalystEstimate
from app.models.stock import Stock
from app.models.transcript import EarningsTranscript

logger = logging.getLogger(__name__)

MODEL = settings.opus_model

SYSTEM_PROMPT = """You are a senior equity analyst building the ASSUMPTIONS for a driver-based
quarterly forecast model. Code will compile your assumptions into an EPS path — you set the inputs,
you do NOT compute EPS yourself.

You will receive: the company's driver history with THROUGH-CYCLE MEDIANS (your reversion anchor),
its business-model archetype, management guidance excerpts, and street consensus.

RULES:
- ALL numbers are FRACTIONS, not percents (operating margin 0.14, NOT 14; revenue YoY +0.12, NOT 12).
- Emit 8-quarter paths for revenue YoY growth and OPERATING MARGIN per scenario.
  revenue_yoy_path[i] is growth vs the same quarter one year earlier (seasonality is handled by
  the compiler — do not re-seasonalize).
- OPERATING MARGIN is the primary profitability driver: code computes operating income =
  revenue × operating_margin (it does NOT decompose gross margin minus opex). Anchor operating_margin
  to the company's RECENT ACTUAL operating margin in the driver table, then project operating leverage
  (margin expansion as it scales, or compression in the bear) per guidance/trend. Do NOT let it drift
  far from recent actuals without an explicit driver — a name running a 14% operating margin does not
  collapse to 5% in the base case. (You MAY also emit gross_margin_path as optional context, but it is
  not used to compute operating income.)
- QUARTER 1 IS USUALLY ALREADY GUIDED (it is the in-progress or just-ended, not-yet-reported
  quarter). Anchor q1 revenue AND operating margin tightly to management guidance and the most recent
  actual in ALL scenarios — guidance for an ending quarter is rarely off by more than a few percent.
  Your cycle/fade view belongs in quarters 2-8, NOT in q1. A thesis about the future must not rewrite
  a quarter that has effectively already happened.
- ARCHETYPE CONDITIONING:
  * cyclical-commodity / deep-value-turnaround: margins MUST trend toward the through-cycle median
    over the horizon unless specific guidance says otherwise — peak margins are not a plateau.
    State which it is.
  * secular-grower / platform: growth FADES over the horizon (no perpetual +30%); say your fade.
  * mature-compounder / financial: stability is the prior; deviations need explicit drivers.
- Scenarios must be genuinely distinct and ordered: bear ≤ base ≤ bull on revenue growth and
  margins, quarter by quarter. Bear = things going wrong plausibly, not Armageddon.
- EVERY material assumption needs a basis: "guidance" (management said it — quote/paraphrase),
  "trend" (visible in the driver history), or "judgment" (your call — defend it). If guidance and
  the through-cycle anchor disagree, say which you weighted and why.
- net_factor = net income / operating income (taxes + below-the-line), one number per scenario.
- share_change_qoq: per-quarter fractional change in diluted shares (buybacks negative, dilution
  positive) — read the share-count trend in the driver table.

Respond with valid JSON only, this exact schema:
{
  "ticker": "string",
  "scenarios": {
    "base": {
      "revenue_yoy_path": [8 fractions],
      "operating_margin_path": [8 fractions],
      "gross_margin_path": [8 fractions]  (OPTIONAL context; omit if not filed),
      "net_factor": fraction,
      "share_change_qoq": fraction,
      "rationale": "string — the 2-3 sentence story of this path"
    },
    "bull": { same shape },
    "bear": { same shape }
  },
  "assumption_bases": [
    {"assumption": "string", "basis": "guidance | trend | judgment", "note": "string — the cite or defense"}
  ],
  "key_swing_factors": ["string — what moves the answer most"]
}"""


async def build_assumptions_context(db: AsyncSession, ticker: str, drivers: DriverHistory) -> str:
    """Driver table + archetype + guidance + consensus — everything the assumptions call reads."""
    sections = [format_drivers_for_llm(drivers)]

    stock = await db.get(Stock, ticker)
    if stock and stock.archetype:
        sections.append(f"--- ARCHETYPE ---\n{stock.archetype}"
                        + (f" — {stock.archetype_rationale}" if stock.archetype_rationale else ""))

    t = (
        await db.execute(
            select(EarningsTranscript)
            .where(EarningsTranscript.ticker == ticker)
            .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if t and isinstance(t.summary, dict) and t.summary.get("guidance"):
        sections.append("--- MANAGEMENT GUIDANCE (latest call) ---\n"
                        + json.dumps(t.summary["guidance"], indent=1, default=str)[:2500])

    est = (
        await db.execute(
            select(AnalystEstimate)
            .where(AnalystEstimate.ticker == ticker,
                   AnalystEstimate.period_end_date >= date.today())
            .order_by(AnalystEstimate.period_end_date.asc())
            .limit(4)
        )
    ).scalars().all()
    if est:
        lines = ["--- STREET CONSENSUS (low-weight reference; do not anchor blindly) ---"]
        for e in est:
            lines.append(
                f"  ~{e.period_end_date}: EPS {e.eps_consensus if e.eps_consensus is not None else 'n/a'}, "
                f"revenue {f'${e.revenue_consensus/1e9:.2f}B' if e.revenue_consensus else 'n/a'} "
                f"({e.number_of_analysts or '?'} analysts, {e.revisions_30d if e.revisions_30d is not None else '?'} revisions/30d)"
            )
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _call_llm(system: str, user: str) -> dict:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(model=MODEL, max_tokens=4096, system=system,
                                  messages=[{"role": "user", "content": user}])
    content = resp.content[0].text
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


async def generate_assumptions(db: AsyncSession, ticker: str, drivers: DriverHistory) -> dict:
    """One Opus call → the raw assumptions payload (clamping happens in model.ScenarioPath)."""
    context = await build_assumptions_context(db, ticker, drivers)
    user = (f"Today's date is {date.today().isoformat()}.\n\n"
            f"Build the 8-quarter forecast assumptions for {ticker}.\n\n{context}\n\n"
            f"Respond with JSON only.")
    out = await asyncio.to_thread(_call_llm, SYSTEM_PROMPT, user)
    logger.info("[forecast] %s: assumptions generated (%d bases cited)",
                ticker, len(out.get("assumption_bases") or []))
    return out
