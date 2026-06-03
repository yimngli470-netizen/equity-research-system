"""Judge Agent — reconciles the bull and bear cases into a leaning (roadmap 2.1).

The judge MUST engage every bear point (it cannot dismiss the bear because momentum or the quant
screen is positive). This is the structural fix for P2: skepticism is forced into the verdict rather
than averaged away.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.synthesis import build_judge_context


class JudgeAgent(BaseAgent):
    agent_type = "judge"
    max_age_days = 1
    model = "claude-opus-4-20250514"

    async def build_context(self, db: AsyncSession, ticker: str) -> str:
        return await build_judge_context(db, ticker)

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
- Your conviction must reflect UNRESOLVED bear risk. If serious bear points stand un-rebutted, your
  conviction must be low even if you lean bullish.
- Reason from the evidence provided; bring domain knowledge but don't invent facts.

Respond with valid JSON only, this exact schema:
{
  "ticker": "string",
  "leaning": "strong_bull | bull | neutral | bear | strong_bear",
  "conviction": 0.0-1.0,            // honest, reflects unresolved bear risk
  "synthesis": "string — 3-5 sentences: what the debate comes down to and where you land",
  "bear_points_addressed": [
    {"point": "string", "assessment": "conceded | rebutted | partial",
     "reasoning": "string — your evidence-based response to this specific bear point"}
  ],
  "bull_points_addressed": [
    {"point": "string", "assessment": "accepted | discounted | partial", "reasoning": "string"}
  ],
  "decisive_factors": ["string — what actually drove your leaning"],
  "what_would_change_my_mind": ["string — concrete, observable events that would flip the call"],
  "verdict_summary": "string — one sentence the user can act on, stated with appropriate humility"
}

If a case is marked unavailable, say so in the synthesis and lower your conviction accordingly."""

    def get_user_prompt(self, ticker: str, context: str) -> str:
        return (f"Adjudicate the bull vs bear debate for {ticker}. Address every bear point.\n\n"
                f"{context}\n\nRespond with JSON only.")
