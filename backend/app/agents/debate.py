"""Debate agent — the bull and bear cases from ONE Opus call (roadmap 2.1).

Bull and bear argue the SAME evidence pack, so they don't need two separate Opus calls: a single
"dual-advocate" call produces both cases at once, and we persist them as the usual `bull` and `bear`
report rows. The judge, the UI, the AI-feature extractor, and the e2e all keep reading two
independent rows — nothing downstream knows the difference — but the per-pipeline Opus count drops by
one (this was 2 calls, now 1). The advocacy is still genuinely two-sided: the prompt demands the
strongest HONEST case for each side, each rated by the same evidence-strength conviction band.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.synthesis import build_evidence_pack
from app.models.analysis import AnalysisReport

logger = logging.getLogger(__name__)


class DebateAgent(BaseAgent):
    """One Opus call → both the bull case and the bear case, persisted as two rows."""

    agent_type = "debate"          # for logging only; it writes `bull` and `bear`, not `debate`
    max_age_days = 1
    model = "claude-opus-4-20250514"

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        return await build_evidence_pack(db, ticker)

    async def run(self, db: AsyncSession, ticker: str, force: bool = False) -> dict:
        """Produce + persist the bull and bear reports from a single call. Returns {"bull","bear"}."""
        if not force:
            cached = await self._cached_pair(db, ticker)
            if cached is not None:
                logger.info("[debate] using cached bull/bear for %s", ticker)
                return cached

        context = await self.build_context(db, ticker)
        user_prompt = await self._augment_user_prompt(db, ticker, self.get_user_prompt(ticker, context))
        combined = await asyncio.to_thread(self._call_claude, self.get_system_prompt(), user_prompt)

        if isinstance(combined, dict) and "error" in combined:
            # Persist the error to both rows so the orchestrator surfaces a failure, not silence.
            await self._save_report_as(db, ticker, "bull", combined)
            await self._save_report_as(db, ticker, "bear", combined)
            return {"bull": combined, "bear": combined}

        bull = self._finalize(combined.get("bull") if isinstance(combined, dict) else None, ticker)
        bear = self._finalize(combined.get("bear") if isinstance(combined, dict) else None, ticker)
        await self._save_report_as(db, ticker, "bull", bull)
        await self._save_report_as(db, ticker, "bear", bear)
        return {"bull": bull, "bear": bear}

    def _finalize(self, side: dict | None, ticker: str) -> dict:
        """Stamp the ticker and clamp the self-rated conviction to [0,1] (gate/sizer hygiene)."""
        side = dict(side) if isinstance(side, dict) else {"error": "missing case in debate response"}
        if "error" in side:
            return side
        side["ticker"] = ticker
        conv = side.get("conviction")
        if isinstance(conv, (int, float)):
            side["conviction"] = max(0.0, min(1.0, float(conv)))
        return side

    async def _cached_pair(self, db: AsyncSession, ticker: str) -> dict | None:
        """Return {"bull","bear"} if BOTH are fresh (within max_age_days) and error-free, else None."""
        from datetime import date, timedelta
        cutoff = date.today() - timedelta(days=self.max_age_days)
        out: dict = {}
        for side in ("bull", "bear"):
            row = (
                await db.execute(
                    select(AnalysisReport)
                    .where(AnalysisReport.ticker == ticker, AnalysisReport.agent_type == side,
                           AnalysisReport.run_date >= cutoff)
                    .order_by(AnalysisReport.run_date.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not row or not isinstance(row.report, dict) or "error" in row.report:
                return None
            out[side] = row.report
        return out

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return (f"Argue BOTH sides of {ticker} from the SAME evidence below: the strongest honest "
                f"BULL case and the strongest honest BEAR case. Stress-test the cycle/peak-earnings "
                f"angle in the bear case.\n\n{context}\n\nRespond with JSON only.")

    def get_system_prompt(self) -> str:
        return """You are a DUAL ADVOCATE running an internal investment debate. In ONE response you
build BOTH the strongest case to OWN the stock (BULL) and the strongest case to AVOID/SHORT it
(BEAR), each argued honestly from the SAME evidence. Argue each side as hard as a dedicated analyst
would — do not soften one to favour the other; a downstream judge will reconcile them.

For BOTH sides:
- Cite specific evidence for every claim (a number, a trend, a transcript point, an analyst finding).
  If you can't cite it, don't claim it. Vague optimism / reflexive pessimism is worthless.
- Engage the actual business. If it's a cyclical, the BULL must address WHY the cycle has room to run
  and the BEAR must test whether current earnings/margins are at a cycle PEAK (a low P/E on peak
  earnings is a trap — value it on normalized/mid-cycle earnings).
- Distinguish what's already priced in from the genuine, under-appreciated edge.

CONVICTION (each side, independently) — pick from the band matching how much HARD evidence the case
rests on. Do NOT default to a round middle number; a forced case must score low:
    0.80-0.95  nearly every key point backed by hard, specific data; little rides on assumption
    0.60-0.75  core points evidenced, but 1-2 lean on judgment or forward assumptions
    0.40-0.55  the case needs several things to break its way; evidence is mixed or thin
    0.20-0.35  a forced case — arguing a side the evidence barely supports

Respond with valid JSON only, this exact schema:
{
  "bull": {
    "ticker": "string",
    "thesis": "string — the bull case in 2-3 sentences",
    "bull_points": [
      {"claim": "string", "evidence": "string — the specific data/finding behind it",
       "importance": "high | medium | low"}
    ],
    "key_drivers": ["string — what has to go right for the bull case"],
    "upside_scenario": "string — what the next 12-24 months look like if the bull is right",
    "bull_fair_value": number,        // bull-case fair value per share, or null if not estimable
    "whats_priced_in": "string — what the market already reflects (so the edge is the rest)",
    "conviction": 0.0-1.0             // from the evidence-strength band above
  },
  "bear": {
    "ticker": "string",
    "thesis": "string — the bear case in 2-3 sentences",
    "bear_points": [
      {"claim": "string", "evidence": "string — the specific data/finding behind it",
       "severity": "high | medium | low"}
    ],
    "key_risks": ["string — the risks that would break the thesis"],
    "downside_scenario": "string — what the next 12-24 months look like if the bear is right",
    "bear_fair_value": number,        // bear-case fair value per share, or null if not estimable
    "cycle_warning": "string — if cyclical: where in the cycle + the normalized-earnings view; else null",
    "conviction": 0.0-1.0             // from the evidence-strength band above
  }
}"""
