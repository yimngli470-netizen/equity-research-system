"""Transcript filtering for the validation agent only.

The earnings/industry/valuation agents read the LLM-generated structured
summary stored in `earnings_transcripts.summary` (see transcript_summarizer.py).
The validation agent deliberately does NOT read the summary — it verifies
agent claims against the *raw* transcript so it can catch summarizer
hallucinations as well. That's why we keep keyword filtering: the validator
needs a budget-friendly slice of the raw text.

Approach: keyword-based paragraph scoring (no LLM calls).
"""

import logging
import re

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs, filtering out very short fragments."""
    paragraphs = re.split(r"\n\s*\n|\n(?=[A-Z])", text)
    return [p.strip() for p in paragraphs if len(p.strip()) > 50]


def _score_paragraph(paragraph: str, keywords: list[str], bonus_keywords: list[str] | None = None) -> float:
    """Score a paragraph by keyword density."""
    text_lower = paragraph.lower()
    score = 0.0

    for kw in keywords:
        score += text_lower.count(kw.lower())

    if bonus_keywords:
        for kw in bonus_keywords:
            score += text_lower.count(kw.lower()) * 1.5

    # Bonus for paragraphs containing numbers (likely quantitative)
    numbers = re.findall(r"\$[\d,.]+|\d+\.?\d*%|\d{1,3}(?:,\d{3})+", paragraph)
    score += len(numbers) * 0.5

    word_count = len(paragraph.split())
    if word_count > 0:
        score = score / (word_count ** 0.5)

    return score


def _select_top_paragraphs(paragraphs: list[str], scores: list[float], max_tokens: int) -> tuple[str, dict]:
    """Pick highest-scoring paragraphs that fit the token budget, keep original order."""
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

    selected_indices = set()
    selected_scores: list[float] = []
    total_tokens = 0

    for idx, score in indexed:
        tokens = _estimate_tokens(paragraphs[idx])
        if total_tokens + tokens > max_tokens:
            continue
        selected_indices.add(idx)
        selected_scores.append(score)
        total_tokens += tokens

    result = [paragraphs[i] for i in sorted(selected_indices)]
    stats = {
        "paragraphs_total": len(paragraphs),
        "paragraphs_selected": len(selected_indices),
        "tokens_estimated": total_tokens,
        "tokens_budget": max_tokens,
        "top_score": max(selected_scores) if selected_scores else 0.0,
        "min_selected_score": min(selected_scores) if selected_scores else 0.0,
    }
    return "\n\n".join(result), stats


FINANCIAL_KEYWORDS = [
    "revenue", "earnings", "profit", "margin", "growth", "decline",
    "operating", "cash flow", "eps", "guidance", "outlook", "forecast",
    "segment", "division", "business unit", "year-over-year", "yoy",
    "quarter", "sequential", "basis points", "billion", "million",
]


def prepare_earnings_context(
    prepared_remarks: str | None,
    qa_section: str | None,
    max_tokens: int = 5000,
) -> str:
    """Filter raw transcript text for the validation agent.

    Returns paragraphs densest in financial figures, segment breakdowns,
    one-time items, and management commentary. Used so the validator can
    cross-check agent claims against source quotes within a token budget.
    """
    parts = []

    if prepared_remarks:
        remarks_budget = max_tokens * 3 // 5  # 60% to prepared remarks
        paragraphs = _split_paragraphs(prepared_remarks)
        scores = [
            _score_paragraph(p, FINANCIAL_KEYWORDS, bonus_keywords=["segment", "one-time", "non-recurring", "restructuring"])
            for p in paragraphs
        ]
        filtered, stats = _select_top_paragraphs(paragraphs, scores, remarks_budget)
        logger.info(
            "[transcript_filter:validator/remarks] %d/%d paragraphs selected, %d/%d tokens (top score %.2f)",
            stats["paragraphs_selected"], stats["paragraphs_total"],
            stats["tokens_estimated"], stats["tokens_budget"], stats["top_score"],
        )
        if filtered:
            parts.append("=== PREPARED REMARKS (key excerpts) ===\n" + filtered)

    if qa_section:
        qa_budget = max_tokens * 2 // 5  # 40% to Q&A
        paragraphs = _split_paragraphs(qa_section)
        scores = [
            _score_paragraph(p, FINANCIAL_KEYWORDS, bonus_keywords=["concern", "risk", "surprised", "disappointing", "strong"])
            for p in paragraphs
        ]
        filtered, stats = _select_top_paragraphs(paragraphs, scores, qa_budget)
        logger.info(
            "[transcript_filter:validator/qa] %d/%d paragraphs selected, %d/%d tokens (top score %.2f)",
            stats["paragraphs_selected"], stats["paragraphs_total"],
            stats["tokens_estimated"], stats["tokens_budget"], stats["top_score"],
        )
        if filtered:
            parts.append("=== ANALYST Q&A (key exchanges) ===\n" + filtered)

    return "\n\n".join(parts) if parts else ""
