"""Judge Agent — reconciles the bull and bear cases into a leaning (roadmap 2.1).

The judge MUST engage every bear point (it cannot dismiss the bear because momentum or the quant
screen is positive). This is the structural fix for P2: skepticism is forced into the verdict rather
than averaged away.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.synthesis import build_judge_context

logger = logging.getLogger(__name__)


class JudgeAgent(BaseAgent):
    agent_type = "judge"
    max_age_days = 1
    model = "claude-opus-4-20250514"

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        return await build_judge_context(db, ticker)

    async def compute_fingerprint(self, db: AsyncSession, ticker: str) -> dict:
        from app.agents import fingerprints as fp
        # The judge's only inputs are the bull and bear cases: identical cases ⇒ identical verdict.
        # Re-running on unchanged inputs adds conviction NOISE, not information — caching here makes
        # the decision more reproducible, not just cheaper.
        return {
            "bull": await fp.report_marker(db, ticker, "bull"),
            "bear": await fp.report_marker(db, ticker, "bear"),
        }

    def postprocess_report(self, report: dict, ticker: str) -> dict:
        """Hygiene only (the rubric in the prompt does the real anchoring): coerce conviction to a
        float in [0,1] and the bear-point counts to non-negative ints, so the decision gate, the
        position sizer, and the calibration loop never choke on a bad type. Logs — but does NOT
        override — a conviction that contradicts the judge's own unresolved-point count, so a
        rubric drift is visible without silently rewriting the model's call."""
        report = super().postprocess_report(report, ticker)
        if not isinstance(report, dict) or "error" in report:
            return report

        conv = report.get("conviction")
        if isinstance(conv, (int, float)):
            report["conviction"] = max(0.0, min(1.0, float(conv)))

        for k in ("unresolved_bear_points", "total_bear_points"):
            v = report.get(k)
            if isinstance(v, (int, float)):
                report[k] = max(0, int(v))

        # Visibility only — surface a rubric/count mismatch, don't clamp (rubric-anchored by choice).
        unresolved = report.get("unresolved_bear_points")
        conv = report.get("conviction")
        if isinstance(unresolved, int) and isinstance(conv, (int, float)):
            if unresolved >= 2 and conv > 0.6:
                logger.warning("[judge] %s: %d unresolved bear points but conviction %.2f (>0.6) — "
                               "rubric drift", ticker, unresolved, conv)
            elif unresolved == 0 and conv < 0.6:
                logger.warning("[judge] %s: 0 unresolved bear points but conviction %.2f (<0.6) — "
                               "rubric drift", ticker, conv)
        return report

    def get_system_prompt(self) -> str:
        return """You are the JUDGE. You are given a BULL case and a BEAR case, each with evidence.
Your job is to weigh them honestly and reach a leaning — the way a portfolio manager adjudicates a
debate between two analysts.

NON-NEGOTIABLE RULES:
- You MUST address EVERY bear point explicitly: concede it, rebut it with evidence, or call it
  partial — and say why. You may NOT ignore a bear point because momentum, sentiment, or the quant
  screen is positive. An unaddressed bear point means you haven't done your job.
- A strong recent quarter or a high quant screen does NOT settle the debate; for a cyclical at a
  possible peak, the burden is on the BULL to show the cycle has room to run.
- You MUST emit at least 2 KILL CRITERIA: specific, FALSIFIABLE, DATED predictions that would flip
  or break your call — each with the exact metric to watch and a date (or fiscal quarter) by which
  it resolves. "The stock could fall" is NOT a kill criterion; "HBM ASPs decline QoQ for two
  consecutive quarters by Q2 FY2026" is. These make your thesis accountable — they will be graded
  later.
- Reason from the evidence provided; bring domain knowledge but don't invent facts.

HOW TO SET CONVICTION — do this in ORDER, do not skip steps:
  1. Address every bear point first (fill `bear_points_addressed`): each is `conceded`, `rebutted`,
     or `partial`.
  2. Count how many bear points you did NOT fully rebut — i.e. `conceded` or `partial` — and put that
     integer in `unresolved_bear_points` (and the total in `total_bear_points`). A `partial` counts
     as unresolved. Weight by severity: a high-severity point left standing matters far more than a
     low-severity one.
  3. ONLY THEN pick `conviction` from the band that matches your count and evidence quality. Do NOT
     default to a round middle number — the band is mandatory:
       0.80-0.95  every bear point rebutted with HARD, specific data; near-term, resolvable risks
       0.60-0.75  exactly ONE material (high/medium-severity) bear point left unresolved/partial
       0.40-0.55  TWO OR MORE material bear points unresolved, OR the evidence on both sides is thin
       0.20-0.35  a CORE (high-severity) bear point is CONCEDED, or the bull case structurally fails
     Conviction is your confidence in the CALL regardless of direction (a high-conviction `bear` is
     as valid as a high-conviction `bull`). If a case is marked unavailable, drop one band.

Respond with valid JSON only, this exact schema:
{
  "ticker": "string",
  "leaning": "strong_bull | bull | neutral | bear | strong_bear",
  "synthesis": "string — 3-5 sentences: what the debate comes down to and where you land",
  "bear_points_addressed": [
    {"point": "string", "assessment": "conceded | rebutted | partial",
     "reasoning": "string — your evidence-based response to this specific bear point",
     "severity": "high | medium | low"}
  ],
  "bull_points_addressed": [
    {"point": "string", "assessment": "accepted | discounted | partial", "reasoning": "string"}
  ],
  "unresolved_bear_points": 0,       // integer: count of bear points assessed conceded OR partial
  "total_bear_points": 0,            // integer: how many bear points there were
  "conviction": 0.0-1.0,            // pick from the band above that matches your unresolved count
  "decisive_factors": ["string — what actually drove your leaning"],
  "kill_criteria": [
    {"prediction": "string — a specific, FALSIFIABLE, observable event that would flip/break the call",
     "watch_metric": "string — the exact metric or number to watch",
     "by_date": "string — a concrete date (YYYY-MM-DD) or fiscal quarter (e.g. Q2 FY2026) it resolves by",
     "would_confirm": "bull | bear — which case it strengthens if it happens"}
  ],
  "verdict_summary": "string — one sentence the user can act on, stated with appropriate humility"
}

You must provide at least 2 kill_criteria, each dated and falsifiable.

If a case is marked unavailable, say so in the synthesis and lower your conviction accordingly."""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return (f"Adjudicate the bull vs bear debate for {ticker}. Address every bear point.\n\n"
                f"{context}\n\nRespond with JSON only.")
