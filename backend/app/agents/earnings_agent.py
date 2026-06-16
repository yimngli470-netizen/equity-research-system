"""Earnings Analyst Agent — deep dive into quarterly results and trends."""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.transcript_summarizer import format_summary_for_agent
from app.ingestion.computed_metrics import format_for_llm, get_computed_metrics
from app.models.earnings import EarningsEvent
from app.models.estimate import AnalystEstimate
from app.models.key_metric import TickerKeyMetric, TickerKpiValue
from app.models.transcript import EarningsTranscript

logger = logging.getLogger(__name__)


class EarningsAgent(BaseAgent):
    agent_type = "earnings"
    max_age_days = 30  # refresh monthly or when new quarter drops
    tier = "opus"

    async def compute_fingerprint(self, db: AsyncSession, ticker: str) -> dict:
        from app.agents import fingerprints as fp
        # Everything this agent's context reads: a new quarter, transcript, surprise print, KPI
        # extraction, or consensus revision re-runs the deep-dive; otherwise the analysis stands.
        return {
            "financials": await fp.financial_marker(db, ticker),
            "transcript": await fp.transcript_marker(db, ticker),
            "surprises": await fp.surprise_marker(db, ticker),
            "kpis": await fp.kpi_marker(db, ticker),
            "estimates": await fp.estimates_marker(db, ticker),
        }

    async def run(self, db: AsyncSession, ticker: str, force: bool = False, mode: str | None = None) -> dict:
        """Run the LLM agent, then overwrite the beat/miss NUMBERS with deterministic ones computed
        from `earnings_events` (the LLM emitted `avg_surprise_pct` in ambiguous units — see
        `quant/earnings_surprise.py`). Keeps the LLM's narrative; fixes only the measured figures."""
        report = await super().run(db, ticker, force=force, mode=mode)
        if not isinstance(report, dict) or "error" in report:
            return report

        from app.quant.earnings_surprise import eps_surprise_stats
        stats = await eps_surprise_stats(db, ticker)
        if stats is None:
            return report

        bm = dict(report.get("beat_miss_history") or {})
        corrected = {"last_4q_eps_beats": stats.last_4q_eps_beats,
                     "avg_surprise_pct": stats.avg_surprise_pct,  # a FRACTION (0.117 = +11.7%)
                     "trend": stats.trend}
        if {k: bm.get(k) for k in corrected} != corrected:
            bm.update(corrected)
            report["beat_miss_history"] = bm
            await self._save_report(db, ticker, report)  # persist the corrected figures
            logger.info("[earnings] %s: corrected beat/miss → beats=%d avg_surprise=%.3f trend=%s",
                        ticker, stats.last_4q_eps_beats, stats.avg_surprise_pct, stats.trend)
        return report

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        snapshot = await get_computed_metrics(db, ticker)
        context = format_for_llm(snapshot)

        # Add earnings transcript (most recent quarter)
        result = await db.execute(
            select(EarningsTranscript)
            .where(EarningsTranscript.ticker == ticker)
            .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
            .limit(1)
        )
        transcript = result.scalar_one_or_none()
        has_transcript_context = False
        if transcript and transcript.summary:
            block = format_summary_for_agent(transcript.summary, focus="earnings")
            if block:
                has_transcript_context = True
                context += (
                    f"\n\n--- EARNINGS CALL (Q{transcript.quarter} {transcript.year}) ---\n"
                    f"{block}"
                )
        elif transcript:
            # Latest transcript exists but summarizer didn't produce output
            # (transient API/parse failure). Skip transcript context for this run
            # rather than feeding stale or low-quality data to the agent.
            logger.warning(
                "[earnings] %s Q%d %d transcript has no summary — skipping transcript context",
                ticker, transcript.quarter, transcript.year,
            )
        if not has_transcript_context:
            context += (
                "\n\n--- EARNINGS CALL / MANAGEMENT GUIDANCE ---\n"
                "No earnings call transcript, structured guidance, or management commentary is available in the database. "
                "Do not infer next-quarter guidance from historical financials alone; mark forward outlook fields as unknown unless another provided data block supports them."
            )

        # Add beat/miss history (last 4 quarters)
        result = await db.execute(
            select(EarningsEvent)
            .where(EarningsEvent.ticker == ticker)
            .order_by(EarningsEvent.report_date.desc())
            .limit(4)
        )
        events = result.scalars().all()
        if events:
            lines = ["--- EARNINGS SURPRISE HISTORY ---"]
            for e in events:
                beat = ""
                if e.eps_actual is not None and e.eps_estimate is not None:
                    diff = e.eps_actual - e.eps_estimate
                    beat = f"{'beat' if diff >= 0 else 'miss'} by ${abs(diff):.2f}"
                    if e.eps_surprise_pct is not None:
                        beat += f" ({e.eps_surprise_pct:+.1%})"
                lines.append(f"  {e.report_date}: EPS actual={e.eps_actual}, est={e.eps_estimate} → {beat}")
            context += "\n\n" + "\n".join(lines)
        else:
            context += (
                "\n\n--- EARNINGS SURPRISE HISTORY ---\n"
                "No EPS/revenue beat-miss history is available in the database. Set beat_miss_history to null."
            )

        result = await db.execute(
            select(AnalystEstimate)
            .where(AnalystEstimate.ticker == ticker)
            .where(AnalystEstimate.period_end_date >= date.today())
            .order_by(AnalystEstimate.period_end_date.asc())
            .limit(4)
        )
        estimates = result.scalars().all()
        if estimates:
            lines = ["--- ANALYST CONSENSUS ESTIMATES ---"]
            for e in estimates:
                parts = [f"  {e.period_end_date}:"]
                if e.eps_consensus is not None:
                    parts.append(f"EPS consensus=${e.eps_consensus:.2f}")
                if e.revenue_consensus is not None:
                    parts.append(f"Revenue consensus=${e.revenue_consensus / 1e9:.2f}B")
                if e.number_of_analysts:
                    parts.append(f"({e.number_of_analysts} analysts)")
                lines.append(" ".join(parts))
            context += "\n\n" + "\n".join(lines)
        else:
            context += (
                "\n\n--- ANALYST CONSENSUS ESTIMATES ---\n"
                "No forward analyst estimates are available in the database. Do not infer consensus or next-quarter direction from valuation multiples."
            )

        # Per-ticker key metrics — the user has configured 4-6 KPIs that matter
        # specifically for this company. The agent must report on each one in
        # its key_metrics output array, drawing values from whichever data block
        # above contains the answer (transcript, financials, or estimates).
        result = await db.execute(
            select(TickerKeyMetric)
            .where(TickerKeyMetric.ticker == ticker)
            .order_by(TickerKeyMetric.priority.asc(), TickerKeyMetric.metric_name.asc())
        )
        key_metrics = result.scalars().all()
        if key_metrics:
            lines = [
                "--- KEY METRICS TO REPORT ON ---",
                (
                    "For each metric below, populate one row in the key_metrics array "
                    "of your output. Pull the value from the transcript / financials / "
                    "estimates blocks above. If the data above does not contain the value, "
                    "set value=\"not disclosed\" and source=\"unknown\". Preserve the order shown. "
                    "Use the target and warning lines together to decide vs_target:\n"
                    "  - beat: comfortably exceeds target\n"
                    "  - in_line: at or near target, well clear of any warning line\n"
                    "  - close: within ~5% of the warning trip condition (e.g., target >15% YoY, "
                    "warning <15%, actual = 16% → close)\n"
                    "  - warning: at or past the warning trip condition (data has crossed the bear-case red line)\n"
                    "  - miss: significantly below target with no warning defined, OR substantially past the warning\n"
                    "  - unknown: value not disclosed in any provided block\n"
                    "Only emit 'close' or 'warning' for metrics where a warning line is given below; "
                    "for metrics without one, use beat/in_line/miss/unknown."
                ),
            ]
            for km in key_metrics:
                row = f"  [P{km.priority}] {km.metric_name} — {km.definition}"
                if km.target_or_threshold:
                    row += f"\n      target: {km.target_or_threshold}"
                if km.warning_threshold:
                    row += f"\n      warning: {km.warning_threshold}"
                if km.why_it_matters:
                    row += f"\n      why: {km.why_it_matters}"
                lines.append(row)
            context += "\n\n" + "\n".join(lines)

            # Pre-extracted, source-verified KPI values (roadmap 0.5). These were pulled
            # from the transcript/IR text with a verbatim evidence quote — prefer them over
            # re-deriving (avoids unverifiable claims). "not disclosed" here is authoritative.
            kpi_vals = (await db.execute(
                select(TickerKpiValue).where(TickerKpiValue.ticker == ticker)
                .order_by(TickerKpiValue.period_end_date.desc())
            )).scalars().all()
            if kpi_vals:
                latest_period = kpi_vals[0].period_end_date
                vlines = [
                    "--- PRE-EXTRACTED KEY METRIC VALUES (verified against source — use these "
                    "verbatim and cite their source; do NOT re-derive or override them) ---"
                ]
                for k in (v for v in kpi_vals if v.period_end_date == latest_period):
                    vlines.append(
                        f"  {k.metric_name}: {k.value} "
                        f"(vs_target={k.vs_target}, trend={k.trend}, source={k.source})"
                    )
                    if k.evidence_quote:
                        vlines.append(f"      evidence: \"{k.evidence_quote[:200]}\"")
                context += "\n\n" + "\n".join(vlines)

        return context

    def get_system_prompt(self) -> str:
        return """You are a senior equity research analyst specializing in earnings analysis. Given a company's quarterly financial data, earnings call transcript excerpts, and beat/miss history, provide a deep analytical assessment.

Focus on:
1. KEY DRIVERS — What drove the quarter's results? Revenue acceleration/deceleration, margin expansion/contraction, and why.
2. TREND ANALYSIS — Are growth rates improving or deteriorating? Are margins expanding sustainably?
3. EARNINGS QUALITY — Is growth driven by real demand or one-time items? Is FCF tracking net income?
4. RISKS — What could go wrong? Margin pressure, growth deceleration, competitive threats evident in the numbers.
5. FORWARD OUTLOOK — Based on explicit management guidance, transcript commentary, or analyst consensus estimates, what should we expect next quarter?
6. TRANSCRIPT ANALYSIS — If transcript data is provided, analyze management tone, segment-level detail, one-time items mentioned, key analyst concerns from Q&A, and forward guidance specifics.
7. KEY METRICS — If a "KEY METRICS TO REPORT ON" block is provided, you MUST populate one row in the key_metrics output array for each metric listed there, in the same order. Pull values from the transcript / financials / estimates data blocks. If a value isn't disclosed in any provided block, set value="not disclosed" and source="unknown" — do NOT fabricate, infer from unrelated data, or skip the metric.

IMPORTANT: Use ONLY the numbers and facts provided in the data. Do not fabricate or estimate numbers not present in the input. When citing transcript content, stay faithful to what management actually said.
IMPORTANT: If transcript/guidance/consensus data is missing, honestly mark forward-looking fields as "unknown" instead of guessing. Do not classify revenue_direction as "decelerating" or margin_direction as "compressing" solely because current growth or margins are unusually high, cyclical, or may eventually normalize. Use decelerating/compressing only when the provided guidance, consensus, or transcript explicitly supports that direction.

You must respond with valid JSON only, no other text. Use this exact schema:
{
  "ticker": "string",
  "latest_quarter": "string",
  "headline_assessment": "string — one sentence summary",
  "key_drivers": [
    {
      "driver": "string",
      "impact": "strong_positive | positive | neutral | negative | strong_negative",
      "detail": "string"
    }
  ],
  "trend_analysis": {
    "revenue_trend": "accelerating | stable | decelerating",
    "margin_trend": "expanding | stable | compressing",
    "earnings_quality": "high | moderate | low",
    "detail": "string — 2-3 sentences on the overall trajectory"
  },
  "risks": [
    {
      "risk": "string",
      "severity": 0.0-1.0,
      "detail": "string"
    }
  ],
  "forward_outlook": {
    "revenue_direction": "accelerating | stable | decelerating | unknown",
    "margin_direction": "expanding | stable | compressing | unknown",
    "confidence": "high | moderate | low",
    "evidence_source": "management_guidance | analyst_consensus | transcript | financial_trend_only | unavailable",
    "missing_data": ["string — important missing data sources, if any"],
    "detail": "string"
  },
  "transcript_analysis": {
    "management_tone": "confident | cautious | defensive | evasive",
    "key_themes_from_call": ["string"],
    "one_time_items": ["string — description of any non-recurring items mentioned"],
    "segment_highlights": ["string — segment-level performance details"],
    "analyst_concerns": ["string — key concerns raised in Q&A"],
    "forward_guidance_detail": "string — specific guidance given by management"
  },
  "beat_miss_history": {
    "last_4q_eps_beats": 0-4,
    "avg_surprise_pct": number,
    "trend": "improving | stable | deteriorating"
  },
  "key_metrics": [
    {
      "name": "string — copy verbatim from KEY METRICS TO REPORT ON block",
      "value": "string — actual value with unit (e.g. '+39%', '$5.4B', 'not disclosed')",
      "vs_target": "beat | in_line | close | warning | miss | unknown",
      "trend": "up | down | flat | unknown",
      "source": "transcript | financials | estimate | unknown",
      "detail": "string — one short sentence on the read; if vs_target is 'close' or 'warning', explicitly state which warning line the value approaches or breaches"
    }
  ],
  "earnings_quality_score": 0.0-1.0,
  "summary": "string — 3-4 sentence comprehensive assessment"
}

If no transcript data is available, set transcript_analysis fields to null.
If no beat/miss history is available, set beat_miss_history fields to null.
If no KEY METRICS TO REPORT ON block is provided, set key_metrics to an empty array [].
If no transcript/guidance/consensus estimate data is available, set forward_outlook revenue_direction and margin_direction to "unknown", confidence to "low", evidence_source to "unavailable", and list the missing sources in missing_data."""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return f"""Analyze the following financial data for {ticker}. Provide a deep earnings analysis covering key drivers, trends, quality, risks, and forward outlook. If earnings call transcript excerpts are included, analyze management commentary, segment details, and analyst concerns.

{context}

Respond with JSON only."""
