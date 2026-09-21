"""Kill-signal service — the standing per-ticker list of what would break the thesis.

Three ways a signal gets here (see models/kill_signal.py for the status lifecycle):
  1. `generate_kill_signals` — LLM seeding at bootstrap, business-aware, like the KPI defs.
  2. `sync_judge_candidates` — after a judge run, its kill_criteria are offered as `candidate`
     rows for the user to accept / edit / dismiss. Nothing enters `active` without a click.
  3. `create_signal` — typed in by hand.

Everything is idempotent on (ticker, signal): re-running the judge or re-seeding never
duplicates a row, and never resurrects one the user dismissed.
"""

import asyncio
import json
import logging
from datetime import date

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm import make_llm_client
from app.models.analysis import AnalysisReport
from app.models.kill_signal import KillSignalEvaluation, TickerKillSignal

logger = logging.getLogger(__name__)

MODEL = settings.sonnet_model

VALID_SEVERITY = ("critical", "high", "medium")
VALID_STATUS = ("candidate", "active", "tripped", "dismissed")

# Order the UI reads top-to-bottom: what's live first, what needs a decision next.
_STATUS_RANK = {"tripped": 0, "active": 1, "candidate": 2, "dismissed": 3}
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2}


def _clean_severity(value: str | None) -> str:
    v = (value or "").strip().lower()
    return v if v in VALID_SEVERITY else "high"


def _clean_status(value: str | None) -> str:
    v = (value or "").strip().lower()
    return v if v in VALID_STATUS else "active"


def _parse_by_date(value) -> date | None:
    """Kill-criteria dates arrive as ISO or as a fiscal quarter ("Q4 FY2026"). Reuse the thesis
    grader's parser so a candidate's date means exactly what grading will later mean by it."""
    from app.thesis.grading import _parse_by_date as parse

    try:
        return parse(value)
    except Exception:
        return None


def to_dict(row: TickerKillSignal) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "signal": row.signal,
        "rationale": row.rationale,
        "source": row.source,
        "severity": row.severity,
        "status": row.status,
        "by_date": row.by_date.isoformat() if row.by_date else None,
        "origin_as_of": row.origin_as_of.isoformat() if row.origin_as_of else None,
        "tripped_on": row.tripped_on.isoformat() if row.tripped_on else None,
        "tripped_note": row.tripped_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ── Read ─────────────────────────────────────────────────────────────────────


async def _latest_evaluations(db: AsyncSession, ticker: str) -> dict[int, dict]:
    """Newest evaluation per signal — what the evaluator concluded for the last reported quarter."""
    rows = (
        await db.execute(
            select(KillSignalEvaluation)
            .where(KillSignalEvaluation.ticker == ticker.upper())
            .order_by(KillSignalEvaluation.period_end_date.desc(), KillSignalEvaluation.id.desc())
        )
    ).scalars().all()
    out: dict[int, dict] = {}
    for e in rows:
        out.setdefault(e.signal_id, {
            "verdict": e.verdict,
            "period_end_date": e.period_end_date.isoformat() if e.period_end_date else None,
            "evidence_quote": e.evidence_quote,
            "reasoning": e.reasoning,
            "source": e.source,
            "source_url": e.source_url,
        })
    return out


async def list_signals(db: AsyncSession, ticker: str, include_dismissed: bool = False) -> list[dict]:
    stmt = select(TickerKillSignal).where(TickerKillSignal.ticker == ticker.upper())
    if not include_dismissed:
        stmt = stmt.where(TickerKillSignal.status != "dismissed")
    rows = (await db.execute(stmt)).scalars().all()
    evals = await _latest_evaluations(db, ticker)
    rows = sorted(
        rows,
        key=lambda r: (
            _STATUS_RANK.get(r.status, 9),
            _SEVERITY_RANK.get(r.severity, 9),
            r.by_date or date.max,
            r.id,
        ),
    )
    return [to_dict(r) | {"evaluation": evals.get(r.id)} for r in rows]


async def format_for_agent(db: AsyncSession, ticker: str) -> str:
    """The user's STANDING kill signals, as a prompt block for the judge.

    Purpose is de-duplication, not instruction: the judge must still emit its own dated
    kill_criteria (that's what gets graded), but it shouldn't spend one of them restating a
    condition the user is already tracking.
    """
    rows = (
        await db.execute(
            select(TickerKillSignal)
            .where(TickerKillSignal.ticker == ticker.upper())
            .where(TickerKillSignal.status.in_(("active", "tripped")))
        )
    ).scalars().all()
    if not rows:
        return ""

    rows = sorted(rows, key=lambda r: (_SEVERITY_RANK.get(r.severity, 9), r.id))
    lines = [
        "--- STANDING KILL SIGNALS (the user's own watchlist for this name) ---",
        "These are already being tracked. Do NOT restate them as your kill_criteria — propose "
        "NEW, non-overlapping ones. If one of these has already TRIPPED, weigh it in your "
        "adjudication.",
    ]
    for r in rows:
        mark = " [TRIPPED" + (f" {r.tripped_on}" if r.tripped_on else "") + "]" if r.status == "tripped" else ""
        due = f" (by {r.by_date})" if r.by_date else ""
        lines.append(f"  - [{r.severity}]{mark} {r.signal}{due}")
        if r.rationale:
            lines.append(f"      why: {r.rationale}")
    return "\n".join(lines)


# ── Write ────────────────────────────────────────────────────────────────────


async def create_signal(
    db: AsyncSession,
    ticker: str,
    signal: str,
    *,
    rationale: str | None = None,
    severity: str | None = None,
    status: str = "active",
    source: str = "manual",
    by_date: date | None = None,
    origin_as_of: date | None = None,
) -> dict | None:
    """Insert one signal. Returns None if (ticker, signal) already exists — the caller decides
    whether that's an error (manual add) or a no-op (judge sync)."""
    signal = (signal or "").strip()
    if not signal:
        return None

    stmt = (
        insert(TickerKillSignal)
        .values(
            ticker=ticker.upper(),
            signal=signal,
            rationale=(rationale or None),
            source=source,
            severity=_clean_severity(severity),
            status=_clean_status(status),
            by_date=by_date,
            origin_as_of=origin_as_of,
        )
        .on_conflict_do_nothing(constraint="uq_kill_signal_ticker_signal")
        .returning(TickerKillSignal)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    await db.commit()
    return to_dict(row) if row is not None else None


async def update_signal(db: AsyncSession, signal_id: int, **fields) -> dict | None:
    """Patch a signal. Only whitelisted columns; unknown keys are ignored."""
    values: dict = {}
    if "signal" in fields and fields["signal"]:
        values["signal"] = str(fields["signal"]).strip()
    if "rationale" in fields:
        values["rationale"] = fields["rationale"] or None
    if "severity" in fields:
        values["severity"] = _clean_severity(fields["severity"])
    if "status" in fields:
        values["status"] = _clean_status(fields["status"])
    if "by_date" in fields:
        values["by_date"] = _parse_by_date(fields["by_date"])
    if "tripped_note" in fields:
        values["tripped_note"] = fields["tripped_note"] or None

    # Trip/untrip stamps the date automatically so the record can't drift from the status.
    if values.get("status") == "tripped":
        values["tripped_on"] = _parse_by_date(fields.get("tripped_on")) or date.today()
    elif "status" in values:
        values["tripped_on"] = None

    if not values:
        row = await db.get(TickerKillSignal, signal_id)
        return to_dict(row) if row else None

    row = (
        await db.execute(
            update(TickerKillSignal)
            .where(TickerKillSignal.id == signal_id)
            .values(**values)
            .returning(TickerKillSignal)
        )
    ).scalar_one_or_none()
    await db.commit()
    return to_dict(row) if row is not None else None


async def accept_candidate(db: AsyncSession, signal_id: int) -> dict | None:
    """Promote a judge candidate into the standing list. Keeps source='judge' as provenance."""
    return await update_signal(db, signal_id, status="active")


async def delete_signal(db: AsyncSession, signal_id: int) -> bool:
    """Hard-delete. Use for manual mistakes — to reject a judge proposal, set status='dismissed'
    instead, or the next judge run will offer the identical text again."""
    result = await db.execute(
        delete(TickerKillSignal).where(TickerKillSignal.id == signal_id)
    )
    await db.commit()
    return (result.rowcount or 0) > 0


# ── Judge candidates ─────────────────────────────────────────────────────────


async def sync_judge_candidates(db: AsyncSession, ticker: str) -> int:
    """Offer the latest judge run's kill_criteria as candidates. Returns the number of NEW rows.

    Idempotent by construction: `create_signal` conflicts on (ticker, signal), so re-running the
    judge with the same criteria adds nothing, and a criterion the user already accepted,
    dismissed, or edited-in-place is left exactly as they left it.
    """
    ticker = ticker.upper()
    report = (
        await db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.ticker == ticker)
            .where(AnalysisReport.agent_type == "judge")
            .order_by(AnalysisReport.run_date.desc(), AnalysisReport.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if report is None or not isinstance(report.report, dict):
        return 0

    criteria = report.report.get("kill_criteria") or []
    if not isinstance(criteria, list):
        return 0

    added = 0
    for kc in criteria:
        if not isinstance(kc, dict):
            continue
        # Judge schema (judge_agent.py): prediction / watch_metric / by_date / would_confirm.
        # The alternates are tolerance for older reports written under earlier schemas.
        text = kc.get("prediction") or kc.get("criterion") or kc.get("signal")
        if not text:
            continue

        # No severity in the judge schema — derive it from direction: a criterion that would
        # confirm the BEAR case is the one that kills a long thesis.
        confirms = str(kc.get("would_confirm") or "").strip().lower()
        severity = "critical" if confirms == "bear" else "medium"

        rationale_parts = []
        if kc.get("watch_metric"):
            rationale_parts.append(f"Watch: {kc['watch_metric']}")
        if confirms:
            rationale_parts.append(f"Would confirm the {confirms} case.")
        if kc.get("reasoning") or kc.get("rationale"):
            rationale_parts.append(str(kc.get("reasoning") or kc.get("rationale")))

        created = await create_signal(
            db, ticker, str(text),
            rationale=" ".join(rationale_parts) or None,
            severity=kc.get("severity") or severity,
            status="candidate",
            source="judge",
            by_date=_parse_by_date(kc.get("by_date")),
            origin_as_of=report.run_date,
        )
        if created:
            added += 1

    if added:
        logger.info("[kill] %s: %d new judge candidate(s) awaiting review", ticker, added)
    return added


# ── LLM seeding ──────────────────────────────────────────────────────────────

_SYS = """You are an equity analyst defining KILL SIGNALS for a stock — the specific, observable
conditions that would break the long thesis and make you SELL. Not risks, not worries: tripwires.

These signals are checked AUTOMATICALLY each quarter against a fixed evidence set:
  (a) reported quarterly financials — revenue, gross/operating/net margin, EPS, FCF, cash, debt
  (b) the earnings call transcript or press release for the quarter
  (c) previously extracted per-company KPI values
Nothing else is available to the checker. A condition it cannot see is dead weight: it returns
"undetermined" every quarter and never fires.

RULES:
- Every signal MUST be decidable from (a), (b), or (c) alone. Do NOT reference third-party data
  (StatCounter, SimilarWeb, Gartner), court rulings, regulatory decisions, share-price levels, or
  anything a company would not state in its own results.
- FALSIFIABLE and NUMERIC wherever possible — a threshold, a direction, and a duration.
  BAD: "competition intensifies", "the stock falls 30%", "market share erodes per third-party data".
  GOOD: "gross margin below 60% for two consecutive quarters", "Data Center revenue declines QoQ",
  "management withdraws or cuts full-year revenue guidance on the call".
- Management commentary IS fair game when it would appear in the call: guidance cuts, an
  announced customer loss, a disclosed charge or reserve.
- Make them SPECIFIC TO THIS BUSINESS — what actually kills THIS company's thesis, not generic
  financial deterioration.
- 4-6 signals. severity: "critical" (thesis is dead), "high" (materially impaired),
  "medium" (warrants re-underwriting).

Respond with JSON only: {"kill_signals":[{"signal","rationale","severity"}]}"""


def _gen(ticker: str, info: dict) -> list[dict]:
    client = make_llm_client()
    user = (
        f"Company: {info.get('name') or ticker} ({ticker}). Sector: {info.get('sector')}. "
        f"Industry: {info.get('industry')}.\nBusiness: {info.get('summary') or ''}\n\nJSON only."
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=2048, system=_SYS,
        messages=[{"role": "user", "content": user}],
    )
    content = resp.content[0].text
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip()).get("kill_signals", [])


async def generate_kill_signals(
    db: AsyncSession, ticker: str, info: dict, force: bool = False
) -> tuple[str, int]:
    """LLM-seed the standing list. Returns (status, count) for the bootstrap report.

    Skips when the ticker already has signals unless `force` — this is one Sonnet call and it
    must not fire on every pipeline run.
    """
    ticker = ticker.upper()
    existing = (
        await db.execute(
            select(TickerKillSignal.id).where(TickerKillSignal.ticker == ticker).limit(1)
        )
    ).scalar_one_or_none()
    if existing and not force:
        n = (
            await db.execute(
                select(TickerKillSignal).where(TickerKillSignal.ticker == ticker)
            )
        ).scalars().all()
        return "skipped", len(n)
    if not settings.llm_configured:
        return "failed", 0

    try:
        proposals = await asyncio.to_thread(_gen, ticker, info)
    except Exception:
        logger.exception("[kill] generation failed for %s", ticker)
        return "failed", 0
    if not proposals:
        return "failed", 0

    added = 0
    for p in proposals:
        if not isinstance(p, dict) or not p.get("signal"):
            continue
        created = await create_signal(
            db, ticker, str(p["signal"]),
            rationale=p.get("rationale"),
            severity=p.get("severity"),
            status="active",
            source="llm",
        )
        if created:
            added += 1
    return ("ok" if added else "skipped"), added
