"""Fetch earnings call transcripts from FMP and store in DB."""

import logging
import re
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.transcript_summarizer import summarize_transcript
from app.ingestion.fmp_client import get_fmp_client
from app.models.financial import Financial
from app.models.transcript import EarningsTranscript

logger = logging.getLogger(__name__)


def _split_transcript(content: str) -> tuple[str | None, str | None]:
    """Split transcript into prepared remarks and Q&A sections.

    FMP transcripts typically have sections like:
    - Operator/moderator introduction
    - Executive prepared remarks
    - Q&A session (marked by "Question-and-Answer Session" or similar)
    """
    if not content:
        return None, None

    # Common Q&A section markers in earnings transcripts
    qa_patterns = [
        r"(?i)question[\s-]*and[\s-]*answer\s+session",
        r"(?i)Q\s*&\s*A\s+session",
        r"(?i)\boperator\b.*?\bfirst question\b",
        r"(?i)we will now begin the question",
        r"(?i)open the line for questions",
        r"(?i)open it up for questions",
    ]

    split_pos = None
    for pattern in qa_patterns:
        match = re.search(pattern, content)
        if match:
            split_pos = match.start()
            break

    if split_pos and split_pos > 200:
        return content[:split_pos].strip(), content[split_pos:].strip()

    return content, None


def _extract_speakers(content: str) -> dict:
    """Extract speaker names from transcript.

    Looks for patterns like "John Smith -- CEO" or "John Smith - Analyst".
    """
    executives = set()
    analysts = set()

    # Pattern: "Name -- Title" or "Name - Company" at start of a line/paragraph
    speaker_pattern = re.compile(
        r"^([A-Z][a-zA-Z\s\.]+?)\s*[-–—]+\s*(.+?)$", re.MULTILINE
    )
    for match in speaker_pattern.finditer(content):
        name = match.group(1).strip()
        role = match.group(2).strip().lower()
        if len(name) < 3 or len(name) > 50:
            continue
        if any(t in role for t in ["ceo", "cfo", "coo", "president", "chief", "vp", "director", "officer"]):
            executives.add(name)
        elif any(t in role for t in ["analyst", "research", "capital", "securities", "bank", "partners"]):
            analysts.add(name)

    return {
        "executives": sorted(executives),
        "analysts": sorted(analysts),
    }


async def ingest_transcripts(db: AsyncSession, ticker: str) -> int:
    """Fetch recent earnings transcripts from FMP.

    Fetches up to 2 most recent quarters. Skips quarters already in DB.
    Returns number of transcripts stored.
    """
    client = get_fmp_client()
    if not client:
        return 0

    # Determine the 2 most recent quarter-end dates from financials
    result = await db.execute(
        select(Financial.period_end_date)
        .where(Financial.ticker == ticker)
        .order_by(Financial.period_end_date.desc())
        .limit(2)
    )
    quarters = result.scalars().all()

    if not quarters:
        logger.info("No financial data for %s, skipping transcript ingestion", ticker)
        return 0

    stored = 0
    for period_end in quarters:
        year = period_end.year
        quarter = (period_end.month - 1) // 3 + 1

        # Check if we already have this transcript
        existing = await db.execute(
            select(EarningsTranscript.id).where(
                EarningsTranscript.ticker == ticker,
                EarningsTranscript.year == year,
                EarningsTranscript.quarter == quarter,
            )
        )
        if existing.scalar_one_or_none() is not None:
            logger.debug("Transcript already exists for %s Q%d %d", ticker, quarter, year)
            continue

        logger.info("Fetching transcript for %s Q%d %d", ticker, quarter, year)
        data = await client.get_earnings_transcript(ticker, year, quarter)
        if not data or not data.get("content"):
            logger.info("No transcript available for %s Q%d %d", ticker, quarter, year)
            continue

        content = data["content"]
        prepared, qa = _split_transcript(content)
        speakers = _extract_speakers(content)

        # Parse transcript date
        transcript_date = None
        date_str = data.get("date")
        if date_str:
            try:
                transcript_date = datetime.fromisoformat(date_str.split(" ")[0]).date()
            except (ValueError, TypeError):
                transcript_date = period_end

        # Summarize first (one Sonnet call) so consumers get a structured view
        # instead of keyword-filtered raw text. Failures here don't block storage.
        summary = await summarize_transcript(ticker, year, quarter, content)

        stmt = insert(EarningsTranscript).values(
            ticker=ticker,
            year=year,
            quarter=quarter,
            transcript_date=transcript_date or period_end,
            full_text=content,
            prepared_remarks=prepared,
            qa_section=qa,
            speakers=speakers,
            summary=summary,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_transcript_ticker_yr_q",
            set_={
                "full_text": stmt.excluded.full_text,
                "prepared_remarks": stmt.excluded.prepared_remarks,
                "qa_section": stmt.excluded.qa_section,
                "speakers": stmt.excluded.speakers,
                "summary": stmt.excluded.summary,
                "transcript_date": stmt.excluded.transcript_date,
            },
        )
        await db.execute(stmt)
        stored += 1

    if stored:
        await db.commit()
        logger.info("Stored %d transcript(s) for %s", stored, ticker)

    return stored
