"""Fetch earnings call transcripts with a FMP → IR scraper fallback chain.

For each (ticker, year, quarter) missing from earnings_transcripts:
  1. Calendar gate — skip if today is outside [period_end + 14d, period_end + 120d]
  2. Tier 1: FMP API (covers mega-caps reliably)
  3. Tier 2: IR site scraper (configured per-ticker in ir/sources.yaml)
  4. Store with provenance: source ("fmp" / "ir_pdf" / "ir_html" / "ir_pptx"),
     source_url, has_qa.

See CLAUDE.md → Transcript Fallback Chain.
"""

import logging
import re
import asyncio
from datetime import date, datetime, timedelta

import yfinance as yf
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.transcript_summarizer import summarize_transcript
from app.ingestion.fmp_client import FMPAccessError, FMPRateLimitError, get_fmp_client
from app.ingestion.ir.fetcher import IRFetchResult, fetch_transcript_from_ir
from app.models.financial import Financial
from app.models.transcript import EarningsTranscript

logger = logging.getLogger(__name__)

# Calendar gate window relative to a quarter's period_end date.
# Lower bound: transcripts typically appear 2-8 weeks after quarter close.
# Upper bound: after ~4 months, if it isn't published, it isn't coming.
_GATE_MIN_DAYS = 14
_GATE_MAX_DAYS = 120


async def _get_fiscal_year_end_month(ticker: str) -> int | None:
    """Infer fiscal year-end month from yfinance metadata."""
    try:
        info = await asyncio.to_thread(lambda: yf.Ticker(ticker).info)
    except Exception:
        logger.exception("Failed to fetch fiscal year metadata for %s", ticker)
        return None

    for key in ("lastFiscalYearEnd", "nextFiscalYearEnd"):
        ts = info.get(key) if info else None
        if ts:
            try:
                return datetime.utcfromtimestamp(int(ts)).date().month
            except (TypeError, ValueError, OSError):
                continue
    return None


def _fiscal_period_from_end_date(
    period_end: date,
    fiscal_year_end_month: int | None,
) -> tuple[int, int]:
    """Return fiscal year/quarter for a period-end date.

    Falls back to calendar quarter when fiscal-year metadata is unavailable.
    """
    if fiscal_year_end_month is None:
        return period_end.year, (period_end.month - 1) // 3 + 1

    fiscal_start_month = fiscal_year_end_month % 12 + 1
    month_offset = (period_end.month - fiscal_start_month) % 12
    quarter = month_offset // 3 + 1
    year = period_end.year if period_end.month <= fiscal_year_end_month else period_end.year + 1
    return year, quarter


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


def _within_gate(period_end: date) -> bool:
    """Calendar gate: only attempt fetch when within the realistic publication window."""
    days_since = (date.today() - period_end).days
    return _GATE_MIN_DAYS <= days_since <= _GATE_MAX_DAYS


async def _try_fmp(ticker: str, year: int, quarter: int) -> dict | None:
    """Tier 1: FMP. Returns a normalized dict or None.

    Returns None (so the orchestrator falls through to IR) on any FMP-side miss:
    no client, no data, subscription gate (402/403), or rate limit.
    """
    client = get_fmp_client()
    if not client:
        return None
    try:
        data = await client.get_earnings_transcript(ticker, year, quarter)
    except FMPAccessError as e:
        logger.info("FMP transcript unavailable for %s Q%d %d — falling through to IR: %s",
                    ticker, quarter, year, e)
        return None
    except FMPRateLimitError as e:
        logger.warning("FMP rate-limited for %s Q%d %d — falling through to IR: %s",
                       ticker, quarter, year, e)
        return None
    if not data or not data.get("content"):
        return None
    transcript_date = None
    date_str = data.get("date")
    if date_str:
        try:
            transcript_date = datetime.fromisoformat(date_str.split(" ")[0]).date()
        except (ValueError, TypeError):
            pass
    return {
        "content": data["content"],
        "source": "fmp",
        "source_url": None,
        "has_qa": True,  # FMP transcripts are full call transcripts
        "transcript_date": transcript_date,
    }


async def _try_ir(ticker: str, year: int, quarter: int) -> dict | None:
    """Tier 2: IR site scraper. Returns a normalized dict or None."""
    result: IRFetchResult = await fetch_transcript_from_ir(ticker, year, quarter)
    if not result.success or not result.content:
        if result.error and result.error != "no IR registry entry":
            logger.info("IR fallback failed for %s Q%d %d: %s", ticker, quarter, year, result.error)
        return None
    return {
        "content": result.content,
        "source": result.source_kind,
        "source_url": result.source_url,
        "has_qa": result.has_qa,
        "transcript_date": None,
    }


async def _store(
    db: AsyncSession, ticker: str, year: int, quarter: int,
    period_end: date, fetched: dict,
) -> None:
    """Split, summarize, and upsert a fetched transcript."""
    content = fetched["content"]
    prepared, qa = _split_transcript(content)
    speakers = _extract_speakers(content)
    summary = await summarize_transcript(ticker, year, quarter, content)

    stmt = insert(EarningsTranscript).values(
        ticker=ticker,
        year=year,
        quarter=quarter,
        transcript_date=fetched["transcript_date"] or period_end,
        full_text=content,
        prepared_remarks=prepared,
        qa_section=qa if fetched["has_qa"] else None,
        speakers=speakers,
        summary=summary,
        source=fetched["source"],
        source_url=fetched["source_url"],
        has_qa=fetched["has_qa"],
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
            "source": stmt.excluded.source,
            "source_url": stmt.excluded.source_url,
            "has_qa": stmt.excluded.has_qa,
        },
    )
    await db.execute(stmt)


async def _resummarize_existing(
    db: AsyncSession, row_id: int, ticker: str, year: int, quarter: int, full_text: str,
) -> bool:
    """Re-run the summarizer on a stored transcript whose summary column is NULL.

    Heals rows that landed with summary=NULL because the original summarizer call
    failed (transient Anthropic error, JSON parse failure, rate limit). Without
    this the orchestrator would skip the row forever on subsequent runs.
    """
    new_summary = await summarize_transcript(ticker, year, quarter, full_text)
    if not new_summary:
        logger.warning(
            "Re-summarize attempt for %s Q%d %d returned no output — leaving summary NULL",
            ticker, quarter, year,
        )
        return False
    await db.execute(
        update(EarningsTranscript)
        .where(EarningsTranscript.id == row_id)
        .values(summary=new_summary)
    )
    logger.info("Healed missing summary for %s Q%d %d", ticker, quarter, year)
    return True


async def ingest_transcripts(db: AsyncSession, ticker: str) -> int:
    """Fetch recent transcripts with FMP → IR fallback, gated by earnings calendar.

    Walks the 2 most recent quarter-end dates from financials. For each quarter:
      - if a row exists with a non-null summary: skip
      - if a row exists with summary=NULL: re-run the summarizer on the stored
        full_text (no re-download) so a single bad summarizer call doesn't leave
        a permanently broken row
      - else (no row): gate by calendar window, try FMP → IR, store with summary

    Returns the count of rows that were either newly stored or healed.
    """
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

    fiscal_year_end_month = await _get_fiscal_year_end_month(ticker)
    touched = 0

    for period_end in quarters:
        year, quarter = _fiscal_period_from_end_date(period_end, fiscal_year_end_month)

        existing = await db.execute(
            select(
                EarningsTranscript.id,
                EarningsTranscript.summary,
                EarningsTranscript.full_text,
            ).where(
                EarningsTranscript.ticker == ticker,
                EarningsTranscript.year == year,
                EarningsTranscript.quarter == quarter,
            )
        )
        row = existing.first()
        if row is not None:
            row_id, existing_summary, existing_full_text = row
            if existing_summary is None and existing_full_text:
                healed = await _resummarize_existing(
                    db, row_id, ticker, year, quarter, existing_full_text
                )
                if healed:
                    touched += 1
            continue

        if not _within_gate(period_end):
            days_since = (date.today() - period_end).days
            logger.debug(
                "Calendar gate: skipping %s Q%d %d (period_end %s, %d days ago)",
                ticker, quarter, year, period_end, days_since,
            )
            continue

        logger.info("Fetching transcript for %s Q%d %d (FMP → IR fallback)", ticker, quarter, year)

        fetched = await _try_fmp(ticker, year, quarter)
        if fetched is None:
            fetched = await _try_ir(ticker, year, quarter)

        if fetched is None:
            logger.info("No transcript available for %s Q%d %d from any source", ticker, quarter, year)
            continue

        await _store(db, ticker, year, quarter, period_end, fetched)
        touched += 1
        logger.info(
            "Stored transcript for %s Q%d %d (source=%s, has_qa=%s)",
            ticker, quarter, year, fetched["source"], fetched["has_qa"],
        )

    if touched:
        await db.commit()

    return touched
