"""Transcript filtering utilities for agent context windows.

Transcripts can be 10-30K tokens. These functions extract the most
relevant paragraphs for each agent's focus area using keyword-based
scoring (no LLM calls).
"""

import re

# Approximate tokens per character (conservative for English text)
CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs, filtering out very short fragments."""
    paragraphs = re.split(r"\n\s*\n|\n(?=[A-Z])", text)
    return [p.strip() for p in paragraphs if len(p.strip()) > 50]


def _score_paragraph(paragraph: str, keywords: list[str], bonus_keywords: list[str] | None = None) -> float:
    """Score a paragraph by keyword density.

    Higher score = more relevant. Counts keyword occurrences
    relative to paragraph length.
    """
    text_lower = paragraph.lower()
    score = 0.0

    for kw in keywords:
        count = text_lower.count(kw.lower())
        score += count

    if bonus_keywords:
        for kw in bonus_keywords:
            count = text_lower.count(kw.lower())
            score += count * 1.5

    # Bonus for paragraphs containing numbers (likely quantitative)
    numbers = re.findall(r"\$[\d,.]+|\d+\.?\d*%|\d{1,3}(?:,\d{3})+", paragraph)
    score += len(numbers) * 0.5

    # Normalize by paragraph length to avoid favoring very long paragraphs
    word_count = len(paragraph.split())
    if word_count > 0:
        score = score / (word_count ** 0.5)

    return score


def _select_top_paragraphs(paragraphs: list[str], scores: list[float], max_tokens: int) -> str:
    """Select highest-scoring paragraphs that fit within the token budget.

    Preserves original order (not sorted by score) for readability.
    """
    indexed = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)

    selected_indices = set()
    total_tokens = 0

    for idx, _score in indexed:
        tokens = _estimate_tokens(paragraphs[idx])
        if total_tokens + tokens > max_tokens:
            continue
        selected_indices.add(idx)
        total_tokens += tokens

    # Return in original order
    result = [paragraphs[i] for i in sorted(selected_indices)]
    return "\n\n".join(result)


# --- Public API ---

FINANCIAL_KEYWORDS = [
    "revenue", "earnings", "profit", "margin", "growth", "decline",
    "operating", "cash flow", "eps", "guidance", "outlook", "forecast",
    "segment", "division", "business unit", "year-over-year", "yoy",
    "quarter", "sequential", "basis points", "billion", "million",
]

COMPETITIVE_KEYWORDS = [
    "competitor", "competition", "market share", "pricing", "advantage",
    "differentiation", "moat", "barrier", "leadership", "versus",
    "compared to", "ahead of", "behind", "threat", "disruption",
    "customer", "win", "lost", "switching", "landscape",
]

GUIDANCE_KEYWORDS = [
    "guidance", "outlook", "expect", "forecast", "anticipate",
    "target", "goal", "plan", "project", "next quarter", "next year",
    "full year", "fiscal year", "going forward", "long-term", "medium-term",
    "capital expenditure", "capex", "invest", "accelerate", "decelerate",
]


def prepare_earnings_context(
    prepared_remarks: str | None,
    qa_section: str | None,
    max_tokens: int = 5000,
) -> str:
    """Filter transcript for the earnings agent.

    Prioritizes: financial figures, segment breakdowns, one-time items,
    management commentary on results, forward guidance.
    """
    parts = []

    if prepared_remarks:
        remarks_budget = max_tokens * 3 // 5  # 60% to prepared remarks
        paragraphs = _split_paragraphs(prepared_remarks)
        scores = [
            _score_paragraph(p, FINANCIAL_KEYWORDS, bonus_keywords=["segment", "one-time", "non-recurring", "restructuring"])
            for p in paragraphs
        ]
        filtered = _select_top_paragraphs(paragraphs, scores, remarks_budget)
        if filtered:
            parts.append("=== PREPARED REMARKS (key excerpts) ===\n" + filtered)

    if qa_section:
        qa_budget = max_tokens * 2 // 5  # 40% to Q&A
        paragraphs = _split_paragraphs(qa_section)
        scores = [
            _score_paragraph(p, FINANCIAL_KEYWORDS, bonus_keywords=["concern", "risk", "surprised", "disappointing", "strong"])
            for p in paragraphs
        ]
        filtered = _select_top_paragraphs(paragraphs, scores, qa_budget)
        if filtered:
            parts.append("=== ANALYST Q&A (key exchanges) ===\n" + filtered)

    return "\n\n".join(parts) if parts else ""


def extract_competitive_mentions(
    full_text: str | None,
    max_tokens: int = 1500,
) -> str:
    """Filter transcript for the industry agent.

    Extracts paragraphs mentioning competitors, market share,
    pricing dynamics, and competitive positioning.
    """
    if not full_text:
        return ""

    paragraphs = _split_paragraphs(full_text)
    scores = [
        _score_paragraph(p, COMPETITIVE_KEYWORDS, bonus_keywords=FINANCIAL_KEYWORDS[:5])
        for p in paragraphs
    ]
    filtered = _select_top_paragraphs(paragraphs, scores, max_tokens)

    return f"=== TRANSCRIPT: Competitive Mentions ===\n{filtered}" if filtered else ""


def extract_guidance_mentions(
    full_text: str | None,
    max_tokens: int = 1500,
) -> str:
    """Filter transcript for the valuation agent.

    Extracts forward-looking statements, guidance, capex plans,
    and management expectations.
    """
    if not full_text:
        return ""

    paragraphs = _split_paragraphs(full_text)
    scores = [
        _score_paragraph(p, GUIDANCE_KEYWORDS, bonus_keywords=FINANCIAL_KEYWORDS[:5])
        for p in paragraphs
    ]
    filtered = _select_top_paragraphs(paragraphs, scores, max_tokens)

    return f"=== TRANSCRIPT: Forward Guidance ===\n{filtered}" if filtered else ""
