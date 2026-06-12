"""Research-note builder (roadmap 5.1) — the deliverable.

Assembles the professional note from artifacts the pipeline ALREADY produced — decision, price
target, forecast, dialectic, validation, journal, financials — with ZERO new analysis LLM calls.
Pure compilation: rating + PT up top, what-changed diff, thesis, our-numbers-vs-street, the PT
decomposition, the debate, dated kill-criteria, sizing, the name's own track record, a financials
appendix, and a provenance footer. Every number in the note exists in a table somewhere.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AnalysisReport
from app.models.decision import StockDecision
from app.models.financial import Financial
from app.models.forecast import Forecast
from app.models.price import DailyPrice
from app.models.price_target import PriceTarget
from app.models.research_note import ResearchNote
from app.models.score import StockScore
from app.models.stock import Stock
from app.models.thesis import StockThesis

logger = logging.getLogger(__name__)


async def _latest_report(db: AsyncSession, ticker: str, agent_type: str) -> dict | None:
    row = (
        await db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.ticker == ticker, AnalysisReport.agent_type == agent_type)
            .order_by(AnalysisReport.run_date.desc(), AnalysisReport.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row.report if row and isinstance(row.report, dict) and "error" not in row.report else None


def _f(v, spec=",.2f", prefix="", suffix="", na="—"):
    return f"{prefix}{v:{spec}}{suffix}" if isinstance(v, (int, float)) else na


def _pct(v, na="—"):
    return f"{v:+.1%}" if isinstance(v, (int, float)) else na


def _b(v, na="—"):
    return f"${v / 1e9:,.2f}B" if isinstance(v, (int, float)) else na


async def _gather(db: AsyncSession, ticker: str) -> dict:
    """Everything the note needs, from the DB."""
    stock = await db.get(Stock, ticker)
    decision = (
        await db.execute(select(StockDecision).where(StockDecision.ticker == ticker)
                         .order_by(StockDecision.date.desc()).limit(1))
    ).scalar_one_or_none()
    pt = (
        await db.execute(select(PriceTarget).where(PriceTarget.ticker == ticker)
                         .order_by(PriceTarget.as_of.desc()).limit(1))
    ).scalar_one_or_none()
    forecast = (
        await db.execute(select(Forecast).where(Forecast.ticker == ticker)
                         .order_by(Forecast.as_of.desc()).limit(1))
    ).scalar_one_or_none()
    score = (
        await db.execute(select(StockScore).where(StockScore.ticker == ticker)
                         .order_by(StockScore.date.desc()).limit(1))
    ).scalar_one_or_none()
    price = (
        await db.execute(select(DailyPrice.close).where(DailyPrice.ticker == ticker)
                         .order_by(DailyPrice.date.desc()).limit(1))
    ).scalar_one_or_none()
    fins = (
        await db.execute(select(Financial).where(Financial.ticker == ticker)
                         .order_by(Financial.period_end_date.desc()).limit(8))
    ).scalars().all()
    theses = (
        await db.execute(select(StockThesis).where(StockThesis.ticker == ticker)
                         .order_by(StockThesis.as_of.desc()).limit(5))
    ).scalars().all()

    return {
        "stock": stock,
        "decision": decision,
        "pt": pt,
        "forecast": forecast,
        "score": score,
        "price": float(price) if price is not None else None,
        "financials": fins,
        "theses": theses,
        "judge": await _latest_report(db, ticker, "judge"),
        "bull": await _latest_report(db, ticker, "bull"),
        "bear": await _latest_report(db, ticker, "bear"),
        "valuation": await _latest_report(db, ticker, "valuation"),
        "industry": await _latest_report(db, ticker, "industry"),
        "earnings": await _latest_report(db, ticker, "earnings"),
        "validation": await _latest_report(db, ticker, "validation"),
        "news": await _latest_report(db, ticker, "news"),
    }


def _summary_payload(g: dict) -> dict:
    """The compact, diffable fingerprint of the current view."""
    d, pt, fc, judge = g["decision"], g["pt"], g["forecast"], g["judge"] or {}
    sizing = (d.position_sizing if d else None) or {}
    val_summary = ((g["validation"] or {}).get("summary")) or {}
    return {
        "rating": d.final_signal if d else None,
        "confidence": d.confidence if d else None,
        "price_target": pt.price_target if pt else None,
        "upside": pt.upside if pt else None,
        "judge_leaning": judge.get("leaning"),
        "judge_conviction": judge.get("conviction"),
        "ntm_eps": fc.base_ntm_eps if fc else None,
        "eps_vs_street": fc.eps_vs_street_next_q if fc else None,
        "composite": g["score"].composite_score if g["score"] else None,
        "target_weight_pct": sizing.get("target_weight_pct"),
        "reliability": val_summary.get("reliability_score"),
    }


_DIFF_FMT = {
    "rating": ("Rating", lambda v: str(v)),
    "confidence": ("Confidence", lambda v: str(v)),
    "price_target": ("Price target", lambda v: _f(v, ",.0f", "$")),
    "upside": ("Upside", _pct),
    "judge_leaning": ("Judge leaning", lambda v: str(v)),
    "judge_conviction": ("Judge conviction", lambda v: _f(v, ".2f")),
    "ntm_eps": ("NTM EPS (ours)", lambda v: _f(v, ",.2f", "$")),
    "eps_vs_street": ("Next-q vs street", _pct),
    "composite": ("Screen composite", lambda v: _f(v, ".3f")),
    "target_weight_pct": ("Position target", lambda v: _f(v, ".1f", suffix="%")),
    "reliability": ("Validation reliability", lambda v: _f(v, ".2f")),
}


def _diff(prev: dict | None, cur: dict) -> list[str]:
    if not prev:
        return []
    out = []
    for key, (label, fmt) in _DIFF_FMT.items():
        a, b = prev.get(key), cur.get(key)
        if a == b:
            continue
        if isinstance(a, float) and isinstance(b, float) and abs(a - b) < 1e-9:
            continue
        out.append(f"{label}: {fmt(a) if a is not None else '—'} → {fmt(b) if b is not None else '—'}")
    return out


def _render(ticker: str, g: dict, summary: dict, changes: list[str], prior_date: date | None) -> str:
    stock, d, pt, fc = g["stock"], g["decision"], g["pt"], g["forecast"]
    judge, bull, bear = g["judge"] or {}, g["bull"] or {}, g["bear"] or {}
    sizing = (d.position_sizing if d else None) or {}
    price = g["price"]
    today = date.today()

    L: list[str] = []
    name = stock.name if stock else ticker
    L.append(f"# {ticker} — {name}")
    L.append(f"*{today} · {(stock.archetype or 'unclassified') if stock else '?'} · "
             f"{(stock.sector or '') if stock else ''}*")
    L.append("")
    rating = summary["rating"] or "—"
    L.append(f"## {rating} ({summary['confidence'] or '—'}) · "
             f"PT {_f(summary['price_target'], ',.0f', '$')} "
             f"({pt.horizon_months if pt else 12}mo, {_pct(summary['upside'])}) · "
             f"Price {_f(price, ',.2f', '$')}")
    if judge.get("verdict_summary"):
        L.append(f"\n> {judge['verdict_summary']}")

    if changes:
        L.append(f"\n## What changed since {prior_date}")
        L += [f"- {c}" for c in changes]

    # Thesis
    conv = judge.get("conviction")
    unresolved = judge.get("unresolved_bear_points")
    total_bear = judge.get("total_bear_points")
    L.append(f"\n## Investment thesis — judge: {judge.get('leaning', '—')}, "
             f"conviction {_f(conv, '.2f')}"
             + (f" ({unresolved}/{total_bear} bear points unresolved)"
                if unresolved is not None and total_bear is not None else ""))
    if judge.get("synthesis"):
        L.append(judge["synthesis"])
    probs = (pt.probabilities if pt else None) or {}
    if probs:
        L.append(f"\nScenario probabilities: bull {_f(probs.get('bull'), '.0%')} / "
                 f"base {_f(probs.get('base'), '.0%')} / bear {_f(probs.get('bear'), '.0%')} "
                 f"(source: {probs.get('source', '?')})")

    # Our numbers vs street
    if fc:
        L.append("\n## Our numbers vs street")
        L.append("| | ours | street | delta |")
        L.append("|---|---|---|---|")
        L.append(f"| next-q EPS | {_f(fc.base_next_q_eps)} | {_f(fc.street_next_q_eps)} "
                 f"| {_pct(fc.eps_vs_street_next_q)} |")
        L.append(f"| NTM EPS | {_f(fc.base_ntm_eps)} | | |")
        L.append(f"| NTM revenue | {_b(fc.base_ntm_revenue)} | | |")
        if pt:
            L.append(f"| 12-mo target | {_f(pt.price_target, ',.0f', '$')} "
                     f"| {_f(pt.street_target_mean, ',.0f', '$')} | |")
        bases = (fc.assumptions or {}).get("assumption_bases") or []
        if bases:
            counts: dict[str, int] = {}
            for a in bases:
                counts[a.get("basis", "?")] = counts.get(a.get("basis", "?"), 0) + 1
            L.append(f"\n*Forecast assumptions cited: "
                     + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) + ".*")

    # Valuation decomposition
    if pt:
        from app.valuation_model.target import scenario_summary
        legs = scenario_summary(pt.scenarios)
        L.append("\n## Valuation")
        L.append("| | bear | base | bull |")
        L.append("|---|---|---|---|")
        for row_label, key in (("DCF", "dcf"), ("Multiple", "multiple"), ("Blended", "blended")):
            L.append(f"| {row_label} | " + " | ".join(
                _f((legs.get(s) or {}).get(key), ",.0f", "$") for s in ("bear", "base", "bull")) + " |")
        w = pt.wacc or {}
        m = pt.method or {}
        L.append(f"\nWACC {_f(w.get('wacc'), '.1%')} (rf {_f(w.get('risk_free'), '.2%')}, "
                 f"β {_f(w.get('beta'), '.2f')} {w.get('beta_source', '')}) · "
                 f"{_f(m.get('w_dcf'), '.0%')} DCF / {_f(1 - m['w_dcf'], '.0%') if isinstance(m.get('w_dcf'), (int, float)) else '—'} multiples · "
                 f"{m.get('multiple_basis', '')}")
        fchk = m.get("forward_multiple_check")
        if fchk:
            L.append(f"\n*Street-method check: {_f(fchk.get('value'), ',.0f', '$')} "
                     f"(our NTM {_f(fchk.get('ntm_eps'))} × fwd P/E {_f(fchk.get('fwd_pe'), '.1f')}, "
                     f"no reversion).*")

    # The debate
    L.append("\n## The debate")
    for label, case, key, weight_key in (("Bull", bull, "bull_points", "importance"),
                                         ("Bear", bear, "bear_points", "severity")):
        pts = case.get(key) or []
        L.append(f"\n**{label}** (conviction {_f(case.get('conviction'), '.2f')}):")
        for p in pts[:3]:
            L.append(f"- ({p.get(weight_key, '?')}) {p.get('claim', '')}")
    addressed = judge.get("bear_points_addressed") or []
    if addressed:
        tally: dict[str, int] = {}
        for a in addressed:
            tally[a.get("assessment", "?")] = tally.get(a.get("assessment", "?"), 0) + 1
        L.append(f"\n**Judge** addressed {len(addressed)} bear points: "
                 + ", ".join(f"{v} {k}" for k, v in sorted(tally.items())) + ".")

    # Kill criteria
    kcs = judge.get("kill_criteria") or []
    if kcs:
        L.append("\n## Kill criteria — dated, falsifiable")
        for k in kcs:
            L.append(f"- [ ] by **{k.get('by_date', '?')}** — {k.get('prediction', '')} "
                     f"(confirms {k.get('would_confirm', '?')})")

    # Risk flags
    flags = (d.risk_flags if d else None) or []
    if flags:
        L.append(f"\n## Risk flags ({len(flags)})")
        for fl in flags:
            L.append(f"- **{str(fl.get('level', '')).upper()}** {fl.get('message', '')}")

    # Position guidance
    if sizing:
        L.append("\n## Position guidance")
        L.append(f"**{sizing.get('action', '—')}** — target {_f(sizing.get('target_weight_pct'), '.2f')}% "
                 f"(cap {_f(sizing.get('max_weight_pct'), '.0f')}%)")
        if sizing.get("rationale"):
            L.append(f"\n*{sizing['rationale']}*")

    # Track record on this name
    graded = [t for t in g["theses"] if t.outcome]
    if graded:
        L.append("\n## Track record on this name")
        for t in graded[:3]:
            o = t.outcome or {}
            L.append(f"- {t.as_of}: {t.leaning} (conv {_f(t.conviction, '.2f')}) → "
                     f"hit-rate {_f(o.get('hit_rate'), '.0%')}, return {_pct(o.get('realized_return'))}"
                     + (f", vs SPY {_pct(o.get('excess_return'))}" if o.get("excess_return") is not None else ""))
    fc_out = (fc.outcome or {}) if fc else {}
    if fc_out.get("quarters"):
        L.append(f"- Forecast accuracy: MAPE {_f(fc_out.get('mape'), '.1%')} over "
                 f"{len(fc_out['quarters'])} resolved quarter(s)")

    # Financials appendix
    fins = g["financials"]
    if fins:
        L.append("\n## Data appendix — last 8 quarters (EDGAR)")
        L.append("| period | revenue | GM | OM | net income | EPS | FCF |")
        L.append("|---|---|---|---|---|---|---|")
        for r in fins:
            gm = (r.gross_profit / r.revenue) if (r.gross_profit and r.revenue) else None
            om = (r.operating_income / r.revenue) if (r.operating_income and r.revenue) else None
            L.append(f"| {r.period} | {_b(r.revenue)} | {_f(gm, '.1%')} | {_f(om, '.1%')} "
                     f"| {_b(r.net_income)} | {_f(r.eps)} | {_b(r.free_cash_flow)} |")

    # Provenance footer
    val_summary = ((g["validation"] or {}).get("summary")) or {}
    L.append("\n---")
    L.append(f"*Validation: reliability {_f(val_summary.get('reliability_score'), '.2f')} over "
             f"{val_summary.get('total_checks', '—')} deterministic checks · "
             f"forecast as of {fc.as_of if fc else '—'} · PT as of {pt.as_of if pt else '—'} · "
             f"financials: SEC EDGAR · generated locally, deterministic compile, no analysis LLM "
             f"calls in this note.*")
    return "\n".join(L)


async def build_research_note(db: AsyncSession, ticker: str) -> ResearchNote | None:
    """Assemble + persist today's note. None when there's no decision yet (nothing to report)."""
    ticker = ticker.upper()
    g = await _gather(db, ticker)
    if g["decision"] is None:
        logger.info("[note] %s: no decision — no note", ticker)
        return None

    summary = _summary_payload(g)
    prior = (
        await db.execute(
            select(ResearchNote).where(ResearchNote.ticker == ticker,
                                       ResearchNote.as_of < date.today())
            .order_by(ResearchNote.as_of.desc()).limit(1)
        )
    ).scalar_one_or_none()
    changes = _diff((prior.payload or {}).get("summary") if prior else None, summary)
    note_md = _render(ticker, g, summary, changes, prior.as_of if prior else None)

    today = date.today()
    row = (
        await db.execute(
            select(ResearchNote).where(ResearchNote.ticker == ticker, ResearchNote.as_of == today)
        )
    ).scalar_one_or_none()
    if row:
        row.note_md = note_md
        row.payload = {"summary": summary}
        row.changes = changes
    else:
        row = ResearchNote(ticker=ticker, as_of=today, note_md=note_md,
                           payload={"summary": summary}, changes=changes)
        db.add(row)
    await db.commit()
    logger.info("[note] %s: research note built (%d chars, %d changes)",
                ticker, len(note_md), len(changes))
    return row
