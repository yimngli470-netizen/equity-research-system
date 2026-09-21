"""Automatic kill-signal evaluation — did the condition actually happen this quarter?

Runs once per (ticker, reported quarter) inside `ingest_ticker`, right after KPI extraction, on
the same terms as `ingestion/kpi_extractor.py`: one Sonnet call, idempotent per period, every
verdict carries a verbatim evidence quote, and "undetermined" is a valid honest answer rather
than a guess.

A `tripped` verdict flips the signal's status automatically — that is the point of the feature.
Two deliberate asymmetries:

  * It only ever TRIPS. It never un-trips, and it never re-evaluates a signal already tripped.
    A tripwire firing is a decision event; erasing it because a later quarter looked better would
    destroy the record. Un-tripping stays a human action.
  * `approaching` is recorded but does NOT change status. It's the early warning ("one more
    quarter of this and it fires"), surfaced in the UI without crying wolf.

The evidence pack is deliberately wider than the transcript alone, because most kill signals are
quantitative ("margin below X for two consecutive quarters") and need multiple quarters of
reported financials to judge — the transcript alone would force an undetermined.
"""

import asyncio
import json
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm import make_llm_client
from app.models.financial import Financial
from app.models.key_metric import TickerKpiValue
from app.models.kill_signal import KillSignalEvaluation, TickerKillSignal
from app.models.transcript import EarningsTranscript

logger = logging.getLogger(__name__)

MODEL = settings.sonnet_model
MAX_TRANSCRIPT_CHARS = 90_000
_QUARTERS_OF_HISTORY = 6

VALID_VERDICTS = ("tripped", "approaching", "not_tripped", "undetermined")

SYSTEM_PROMPT = """You evaluate KILL SIGNALS for a stock — pre-registered conditions that would
break the investment thesis. You are given the signals and the evidence from the most recently
reported quarter. For EACH signal, decide whether the condition has been MET.

VERDICTS:
  "tripped"      — the condition is clearly and fully met by the evidence
  "approaching"  — measurably close, or partially met (e.g. the condition needs two consecutive
                   quarters and this is the first)
  "not_tripped"  — the evidence shows the condition is NOT met
  "undetermined" — the evidence provided does not let you judge

CRITICAL RULES:
- Use ONLY the evidence provided. Do NOT use outside knowledge, and do NOT infer, estimate, or
  extrapolate a number that isn't there.
- "undetermined" is the CORRECT answer when the data isn't present. It is never a failure to say
  so. Guessing is worse than abstaining — a false "tripped" would wrongly kill a thesis.
- Only answer "tripped" when the condition is met on its own terms. If it specifies a threshold,
  the reported number must actually cross it. If it specifies a duration ("two consecutive
  quarters"), one quarter is "approaching", NOT "tripped".
- evidence_quote must be a VERBATIM span copied from the evidence that establishes your verdict.
  Null it only when the verdict is "undetermined".

Respond with valid JSON only, this exact schema:
{
  "evaluations": [
    {
      "id": <integer — copy the signal's id exactly as given>,
      "verdict": "tripped | approaching | not_tripped | undetermined",
      "evidence_quote": "string — verbatim span from the evidence, or null",
      "reasoning": "string — one or two sentences tying the evidence to the condition"
    }
  ]
}"""


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "n/a"
    for unit, div in (("B", 1e9), ("M", 1e6)):
        if abs(v) >= div:
            return f"${v / div:.2f}{unit}"
    return f"${v:,.0f}"


def _financials_block(rows: list[Financial]) -> str:
    """Reported quarters, newest first, with the derived margins most conditions are written in."""
    lines = ["--- REPORTED QUARTERLY FINANCIALS (newest first) ---"]
    for f in rows:
        gm = f"{f.gross_profit / f.revenue:.1%}" if f.gross_profit and f.revenue else "n/a"
        om = f"{f.operating_income / f.revenue:.1%}" if f.operating_income and f.revenue else "n/a"
        nm = f"{f.net_income / f.revenue:.1%}" if f.net_income and f.revenue else "n/a"
        lines.append(
            f"  {f.period} (ended {f.period_end_date}): revenue={_fmt_money(f.revenue)} "
            f"gross_margin={gm} operating_margin={om} net_margin={nm} "
            f"op_income={_fmt_money(f.operating_income)} net_income={_fmt_money(f.net_income)} "
            f"eps={f.eps if f.eps is not None else 'n/a'} fcf={_fmt_money(f.free_cash_flow)} "
            f"cash={_fmt_money(f.cash_and_equivalents)} debt={_fmt_money(f.total_debt)}"
        )
    return "\n".join(lines)


def _kpi_block(rows: list[TickerKpiValue]) -> str:
    if not rows:
        return ""
    lines = ["--- EXTRACTED KPI VALUES FOR THIS QUARTER ---"]
    for k in rows:
        lines.append(f"  {k.metric_name}: {k.value} (vs target: {k.vs_target}, trend: {k.trend})")
        if k.evidence_quote:
            lines.append(f'      "{k.evidence_quote[:300]}"')
    return "\n".join(lines)


def _call(ticker: str, signals_block: str, evidence: str) -> dict:
    client = make_llm_client()
    user_prompt = (
        f"Evaluate these kill signals for {ticker} against the reported quarter below.\n\n"
        f"KILL SIGNALS:\n{signals_block}\n\n"
        f"EVIDENCE:\n{evidence}\n\nRespond with JSON only."
    )
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=3072, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = resp.content[0].text
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        return json.loads(content.strip())
    except json.JSONDecodeError as e:
        logger.error("[kill_eval] JSON parse failed for %s: %s", ticker, e)
        return {"error": "json_parse_failed"}
    except Exception as e:
        logger.error("[kill_eval] LLM call failed for %s: %s", ticker, e)
        return {"error": str(e)}


async def evaluate_kill_signals(db: AsyncSession, ticker: str, force: bool = False) -> int:
    """Evaluate this ticker's active kill signals against the latest reported quarter.

    Returns the number of signals evaluated (0 when there's nothing to do — no signals, no
    financials, or this period was already evaluated).
    """
    ticker = ticker.upper()

    # Already-tripped signals are excluded: the verdict stands until the user clears it.
    signals = (
        await db.execute(
            select(TickerKillSignal)
            .where(TickerKillSignal.ticker == ticker)
            .where(TickerKillSignal.status == "active")
        )
    ).scalars().all()
    if not signals:
        return 0

    financials = (
        await db.execute(
            select(Financial)
            .where(Financial.ticker == ticker)
            .order_by(Financial.period_end_date.desc())
            .limit(_QUARTERS_OF_HISTORY)
        )
    ).scalars().all()
    if not financials:
        logger.info("[kill_eval] no financials for %s — skipping", ticker)
        return 0
    period_end = financials[0].period_end_date

    if not force:
        # Idempotent per period, and per signal: a signal ADDED after this quarter was evaluated
        # still gets its first verdict rather than waiting a quarter.
        done = set(
            (
                await db.execute(
                    select(KillSignalEvaluation.signal_id)
                    .where(KillSignalEvaluation.ticker == ticker)
                    .where(KillSignalEvaluation.period_end_date == period_end)
                )
            ).scalars().all()
        )
        signals = [s for s in signals if s.id not in done]
        if not signals:
            logger.info("[kill_eval] %s already evaluated for %s — skipping", ticker, period_end)
            return 0

    if not settings.llm_configured:
        return 0

    transcript = (
        await db.execute(
            select(EarningsTranscript)
            .where(EarningsTranscript.ticker == ticker)
            .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    kpis = (
        await db.execute(
            select(TickerKpiValue)
            .where(TickerKpiValue.ticker == ticker)
            .where(TickerKpiValue.period_end_date == period_end)
        )
    ).scalars().all()

    parts = [_financials_block(financials)]
    kpi_text = _kpi_block(kpis)
    if kpi_text:
        parts.append(kpi_text)
    if transcript and transcript.full_text:
        parts.append(
            f"--- EARNINGS CALL / RELEASE (Q{transcript.quarter} {transcript.year}) ---\n"
            f"{transcript.full_text[:MAX_TRANSCRIPT_CHARS]}"
        )
    else:
        parts.append(
            "--- EARNINGS CALL / RELEASE ---\n"
            "No transcript or release text is available for this quarter. Judge only from the "
            "reported financials above; answer 'undetermined' for anything requiring management "
            "commentary or segment detail not shown."
        )
    evidence = "\n\n".join(parts)

    signals_block = "\n".join(
        f"- id={s.id} [{s.severity}] {s.signal}"
        + (f"\n    context: {s.rationale}" if s.rationale else "")
        for s in signals
    )

    result = await asyncio.to_thread(_call, ticker, signals_block, evidence)
    if "error" in result:
        return 0

    by_id = {s.id: s for s in signals}
    today = date.today()
    source = "transcript" if (transcript and transcript.full_text) else "financials"
    source_url = transcript.source_url if (transcript and transcript.full_text) else financials[0].source_url

    rows, tripped_now = [], []
    for e in result.get("evaluations", []):
        sig = by_id.get(e.get("id"))
        if sig is None:
            continue  # hallucinated id — drop it
        verdict = str(e.get("verdict") or "").strip().lower()
        if verdict not in VALID_VERDICTS:
            verdict = "undetermined"
        quote = (e.get("evidence_quote") or None) if verdict != "undetermined" else None
        rows.append({
            "signal_id": sig.id,
            "ticker": ticker,
            "period_end_date": period_end,
            "verdict": verdict,
            "evidence_quote": quote,
            "reasoning": (e.get("reasoning") or None),
            "source": source if quote else "unknown",
            "source_url": source_url if quote else None,
            "as_of": today,
        })
        if verdict == "tripped":
            tripped_now.append((sig, e))

    if not rows:
        return 0

    stmt = insert(KillSignalEvaluation).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_kill_eval_signal_period",
        set_={c: getattr(stmt.excluded, c) for c in
              ("verdict", "evidence_quote", "reasoning", "source", "source_url", "as_of")},
    )
    await db.execute(stmt)

    # Flip the signals the evaluator says fired. The note records WHY, so the panel shows the
    # reason next to the red row without needing a second lookup.
    for sig, e in tripped_now:
        sig.status = "tripped"
        sig.tripped_on = period_end
        note = (e.get("reasoning") or "").strip()
        quote = (e.get("evidence_quote") or "").strip()
        sig.tripped_note = (f"{note} — \"{quote[:300]}\"" if quote else note) or None
        logger.warning("[kill_eval] %s TRIPPED: %s", ticker, sig.signal[:120])

    await db.commit()
    logger.info(
        "[kill_eval] %s @ %s: %d signal(s) evaluated, %d tripped, %d approaching",
        ticker, period_end, len(rows), len(tripped_now),
        sum(1 for r in rows if r["verdict"] == "approaching"),
    )
    return len(rows)
