"""Transcript summarizer — single Sonnet call that turns a raw earnings call
into structured JSON consumed by earnings, industry, and valuation agents.

Why this exists:
- Keyword-based regex filtering is brittle (every company formats transcripts
  differently) and ends up wasting context budget on operator boilerplate.
- One LLM pass produces a clean structured extract that all 3 consuming agents
  share, instead of each agent's keyword filter rediscovering the same facts.
- Transcripts are immutable; we summarize once at ingestion time and cache
  forever in earnings_transcripts.summary (JSONB).

The validation agent does NOT consume this — it still verifies claims against
the raw transcript so the summary's own hallucinations don't get rubber-stamped.
"""

import asyncio
import json
import logging

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)


SUMMARIZER_MODEL = "claude-sonnet-4-20250514"
MAX_INPUT_CHARS = 120_000  # ~30K tokens — Sonnet handles this comfortably
MAX_OUTPUT_TOKENS = 4096


SYSTEM_PROMPT = """You are an analyst extracting structured information from an earnings call transcript. Your job is to read the entire transcript and produce a clean structured JSON summary that downstream analyst agents can consume directly.

Be faithful to what management actually said. Do not infer numbers that aren't stated. When in doubt, mark a field as null rather than guessing.

Quote management directly when capturing tone or specific guidance — verbatim quotes are valuable for downstream cross-referencing.

Respond with ONLY valid JSON, no surrounding prose, using this exact schema:

{
  "headline_metrics": [
    {"metric": "string (e.g. 'Q1 revenue')", "value": "string (e.g. '$56.31B')", "context": "string (e.g. '+23.8% YoY' or null)"}
  ],
  "segments": [
    {"name": "string", "revenue": "string or null", "growth": "string or null", "margin": "string or null", "commentary": "string or null"}
  ],
  "guidance": {
    "next_quarter": "string or null — explicit Q+1 guidance",
    "full_year": "string or null — explicit full-year guidance",
    "long_term": "string or null — multi-year statements (e.g. CapEx 2027)",
    "capex": "string or null — capex specifics if provided"
  },
  "management_tone": "confident | cautious | defensive | evasive | mixed",
  "tone_evidence": "string — 1-2 sentence justification of the tone classification with a paraphrase of supporting language",
  "key_themes": ["string"],
  "one_time_items": ["string — non-recurring items management called out (e.g. legal charge, restructuring)"],
  "competitive_mentions": [
    {"competitor_or_market": "string", "claim": "string — what management said"}
  ],
  "analyst_concerns": ["string — concerns or pushback raised by analysts in Q&A"],
  "verbatim_quotes": [
    {"speaker": "string (name + title if available)", "quote": "string — direct quote, useful for validation"}
  ],
  "risk_signals": ["string — risks management acknowledged or hedged on"],
  "summary_paragraph": "string — 4-6 sentence narrative summary capturing the most important takeaways from the call"
}

Rules:
- Skip operator boilerplate, safe-harbor statements, and "thank you for joining" remarks entirely.
- For 'segments': only include if management broke out segment-level numbers. Don't invent segments.
- For 'verbatim_quotes': pick 4-8 quotes that most matter — guidance, key strategy claims, defensive moments. Each quote should be 1-3 sentences.
- For 'tone_evidence': cite specific language patterns (hedging words, confidence markers, evasion).
- 'headline_metrics' should capture the 5-10 most important numbers reported on the call.
"""


def _call_summarizer(client: anthropic.Anthropic, transcript_text: str, ticker: str, year: int, quarter: int) -> dict:
    """Synchronous Claude call. Wrapped in asyncio.to_thread by the async caller."""
    user_prompt = (
        f"Extract structured information from this {ticker} Q{quarter} {year} earnings call transcript. "
        f"Respond with JSON only.\n\n{transcript_text}"
    )

    try:
        response = client.messages.create(
            model=SUMMARIZER_MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = response.content[0].text

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        return json.loads(content.strip())

    except json.JSONDecodeError as e:
        logger.error("[transcript_summarizer] JSON parse failed for %s Q%d %d: %s", ticker, quarter, year, e)
        return {"error": "json_parse_failed", "raw": content[:1000]}
    except anthropic.APIError as e:
        logger.error("[transcript_summarizer] Claude API error for %s Q%d %d: %s", ticker, quarter, year, e)
        return {"error": f"api_error: {e}"}


async def summarize_transcript(
    ticker: str,
    year: int,
    quarter: int,
    full_text: str,
) -> dict | None:
    """Run a single Sonnet call to extract structured JSON from the transcript.

    Returns the structured dict on success, or None if no API key / no input text.
    On API/parse failures returns a dict with an "error" key (don't store these).
    """
    if not full_text or len(full_text) < 500:
        return None
    if not settings.anthropic_api_key:
        logger.warning("[transcript_summarizer] No ANTHROPIC_API_KEY — skipping %s Q%d %d", ticker, quarter, year)
        return None

    truncated = full_text[:MAX_INPUT_CHARS]
    if len(full_text) > MAX_INPUT_CHARS:
        logger.info(
            "[transcript_summarizer] %s Q%d %d transcript truncated %d → %d chars",
            ticker, quarter, year, len(full_text), MAX_INPUT_CHARS,
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    logger.info("[transcript_summarizer] summarizing %s Q%d %d (%d chars)", ticker, quarter, year, len(truncated))
    summary = await asyncio.to_thread(_call_summarizer, client, truncated, ticker, year, quarter)

    if summary.get("error"):
        logger.error("[transcript_summarizer] returned error for %s Q%d %d", ticker, quarter, year)
        return None

    logger.info(
        "[transcript_summarizer] %s Q%d %d extracted: %d segments, %d quotes, tone=%s",
        ticker, quarter, year,
        len(summary.get("segments", [])),
        len(summary.get("verbatim_quotes", [])),
        summary.get("management_tone"),
    )
    return summary


def format_summary_for_agent(summary: dict, focus: str = "earnings") -> str:
    """Render the structured summary as text for an agent's prompt context.

    `focus` controls what's emphasized:
    - 'earnings': headline metrics, segments, guidance, tone, themes, verbatim quotes
    - 'industry': competitive mentions, themes, market commentary, segments
    - 'valuation': guidance (all sections), headline metrics, capex
    """
    if not summary or summary.get("error"):
        return ""

    parts = ["=== EARNINGS CALL — STRUCTURED SUMMARY ==="]

    if focus == "earnings":
        if summary.get("headline_metrics"):
            parts.append("\nHEADLINE METRICS:")
            for m in summary["headline_metrics"]:
                ctx = f" ({m['context']})" if m.get("context") else ""
                parts.append(f"  - {m.get('metric')}: {m.get('value')}{ctx}")
        if summary.get("segments"):
            parts.append("\nSEGMENTS:")
            for s in summary["segments"]:
                bits = [s.get("name", "?")]
                if s.get("revenue"): bits.append(f"rev={s['revenue']}")
                if s.get("growth"): bits.append(f"growth={s['growth']}")
                if s.get("margin"): bits.append(f"margin={s['margin']}")
                parts.append(f"  - {' | '.join(bits)}")
                if s.get("commentary"):
                    parts.append(f"      ↳ {s['commentary']}")
        if summary.get("guidance"):
            parts.append("\nGUIDANCE:")
            for k, v in summary["guidance"].items():
                if v:
                    parts.append(f"  - {k}: {v}")
        if summary.get("management_tone"):
            parts.append(f"\nMANAGEMENT TONE: {summary['management_tone']}")
            if summary.get("tone_evidence"):
                parts.append(f"  evidence: {summary['tone_evidence']}")
        if summary.get("key_themes"):
            parts.append(f"\nKEY THEMES: {', '.join(summary['key_themes'])}")
        if summary.get("one_time_items"):
            parts.append("\nONE-TIME ITEMS:")
            for item in summary["one_time_items"]:
                parts.append(f"  - {item}")
        if summary.get("analyst_concerns"):
            parts.append("\nANALYST CONCERNS:")
            for c in summary["analyst_concerns"]:
                parts.append(f"  - {c}")
        if summary.get("verbatim_quotes"):
            parts.append("\nKEY QUOTES:")
            for q in summary["verbatim_quotes"]:
                parts.append(f'  {q.get("speaker", "?")}: "{q.get("quote", "")}"')

    elif focus == "industry":
        if summary.get("competitive_mentions"):
            parts.append("\nCOMPETITIVE COMMENTARY:")
            for c in summary["competitive_mentions"]:
                parts.append(f"  - on {c.get('competitor_or_market')}: {c.get('claim')}")
        if summary.get("key_themes"):
            parts.append(f"\nKEY THEMES: {', '.join(summary['key_themes'])}")
        if summary.get("segments"):
            parts.append("\nSEGMENT DYNAMICS:")
            for s in summary["segments"]:
                bits = [s.get("name", "?")]
                if s.get("growth"): bits.append(f"growth={s['growth']}")
                if s.get("commentary"): bits.append(s["commentary"])
                parts.append(f"  - {' | '.join(bits)}")
        if summary.get("risk_signals"):
            parts.append("\nRISK SIGNALS:")
            for r in summary["risk_signals"]:
                parts.append(f"  - {r}")

    elif focus == "valuation":
        if summary.get("guidance"):
            parts.append("\nFORWARD GUIDANCE FROM CALL:")
            for k, v in summary["guidance"].items():
                if v:
                    parts.append(f"  - {k}: {v}")
        if summary.get("headline_metrics"):
            parts.append("\nKEY REPORTED METRICS:")
            for m in summary["headline_metrics"]:
                ctx = f" ({m['context']})" if m.get("context") else ""
                parts.append(f"  - {m.get('metric')}: {m.get('value')}{ctx}")
        if summary.get("management_tone"):
            parts.append(f"\nMANAGEMENT TONE: {summary['management_tone']}")
            if summary.get("tone_evidence"):
                parts.append(f"  evidence: {summary['tone_evidence']}")

    if summary.get("summary_paragraph"):
        parts.append(f"\nNARRATIVE SUMMARY:\n{summary['summary_paragraph']}")

    return "\n".join(parts)
