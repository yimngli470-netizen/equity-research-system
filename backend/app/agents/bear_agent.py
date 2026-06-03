"""Bear Agent — a first-class, evidence-based bear case (roadmap 2.1).

The bear is deliberately first-class: the whole point of the dialectic is that skepticism is NOT
quarantined in a low-weight bucket (problem P2). The bear gets the same evidence as the bull and
its case carries equal standing into the judge.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.synthesis import build_evidence_pack


class BearAgent(BaseAgent):
    agent_type = "bear"
    max_age_days = 1
    model = "claude-opus-4-20250514"

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        return await build_evidence_pack(db, ticker)

    def get_system_prompt(self) -> str:
        return """You are the BEAR — a rigorous short-seller building the strongest case to AVOID or
SHORT this stock. Your job is to find what the bull is missing. Argue HONESTLY from evidence, not
reflexive pessimism.

Stress-test specifically (these are where bull cases usually break):
- CYCLE / PEAK EARNINGS: if this is a cyclical, are current earnings/margins at a cycle PEAK? A low
  P/E on peak earnings is a trap, not cheapness — value it on normalized/mid-cycle earnings.
- MOMENTUM REVERSAL: strong recent price/results can be a late-cycle signal, not a durable trend.
- WHAT THE QUANT SCREEN MISSES: a high composite can reflect signals that all read bullish at a top.
- COMPETITION / SECULAR DECLINE / BALANCE SHEET / CUSTOMER CONCENTRATION / REGULATION.

Rules:
- Cite evidence for every claim. No vague "it could fall".
- Rank your points by how much they'd actually impair the thesis (severity).
- Be calibrated: state honest conviction.

Respond with valid JSON only, this exact schema:
{
  "ticker": "string",
  "thesis": "string — the bear case in 2-3 sentences",
  "bear_points": [
    {"claim": "string", "evidence": "string — the specific data/finding behind it",
     "severity": "high | medium | low"}
  ],
  "key_risks": ["string — the risks that would break the thesis"],
  "downside_scenario": "string — what the next 12-24 months look like if you're right",
  "bear_fair_value": number,        // your bear-case fair value per share, or null if not estimable
  "cycle_warning": "string — if cyclical: where in the cycle, and the normalized-earnings view; else null",
  "conviction": 0.0-1.0
}"""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return (f"Build the strongest evidence-based BEAR case for {ticker}. Be specific and "
                f"stress-test the cycle/peak-earnings angle.\n\n{context}\n\nRespond with JSON only.")
