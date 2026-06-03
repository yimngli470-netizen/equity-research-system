"""Bull Agent — the strongest evidence-based bull case (roadmap 2.1)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.synthesis import build_evidence_pack


class BullAgent(BaseAgent):
    agent_type = "bull"
    max_age_days = 1
    model = "claude-opus-4-20250514"

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        return await build_evidence_pack(db, ticker)

    def get_system_prompt(self) -> str:
        return """You are the BULL — a sharp buy-side analyst building the strongest case to OWN this
stock. Argue for the upside, but argue HONESTLY: every point must rest on specific evidence from the
provided data and analyst findings. A bull case made of vague optimism is worthless.

Rules:
- Cite evidence for every claim (a number, a trend, a transcript point, an analyst finding). If you
  can't cite it, don't claim it.
- Engage the actual business: if it's a cyclical, your bull case must address WHY the cycle has room
  to run, not just that recent results are strong.
- Distinguish what's already priced in from genuine, under-appreciated upside.
- Be calibrated: state your conviction honestly (a forced bull case can have low conviction).

Respond with valid JSON only, this exact schema:
{
  "ticker": "string",
  "thesis": "string — the bull case in 2-3 sentences",
  "bull_points": [
    {"claim": "string", "evidence": "string — the specific data/finding behind it",
     "importance": "high | medium | low"}
  ],
  "key_drivers": ["string — what has to go right for the bull case"],
  "upside_scenario": "string — what the next 12-24 months look like if you're right",
  "bull_fair_value": number,        // your bull-case fair value per share, or null if not estimable
  "whats_priced_in": "string — what the market already reflects (so the edge is the rest)",
  "conviction": 0.0-1.0             // honest confidence in this bull case
}"""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return (f"Build the strongest evidence-based BULL case for {ticker}.\n\n{context}\n\n"
                f"Respond with JSON only.")
