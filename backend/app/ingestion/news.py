"""Fetch factual news from yfinance (free, no API key required).

Filters for STORY content type and extracts factual information only.
"""

import asyncio
import logging
from datetime import date, datetime

import yfinance as yf
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document

logger = logging.getLogger(__name__)


async def ingest_news(db: AsyncSession, ticker: str) -> int:
    """Fetch recent news for a ticker from yfinance and store as documents.

    yfinance returns ~10 recent news items from Yahoo Finance.
    We store STORY type items (articles), skipping VIDEOs and ads.

    Returns number of news documents upserted.
    """
    logger.info("Fetching news for %s", ticker)

    stock = yf.Ticker(ticker)
    news_items = await asyncio.to_thread(lambda: stock.news)

    if not news_items:
        logger.warning("No news returned for %s", ticker)
        return 0

    rows = []
    for item in news_items:
        content = item.get("content", {})

        # Only store articles (STORY), skip videos and other types
        if content.get("contentType") != "STORY":
            continue

        title = content.get("title", "").strip()
        if not title:
            continue

        # Parse publish date
        pub_date_str = content.get("pubDate")
        if pub_date_str:
            try:
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                pub_date = date.today()
        else:
            pub_date = date.today()

        # Build factual summary from available fields
        summary = content.get("summary", "").strip()
        description = content.get("description", "").strip()
        body = summary or description or title

        # Get publisher info
        provider = content.get("provider", {})
        publisher = provider.get("displayName", "Unknown")

        # Get URL
        canonical = content.get("canonicalUrl", {})
        url = canonical.get("url", "")

        rows.append(
            {
                "ticker": ticker,
                "doc_type": "news",
                "date": pub_date,
                "title": title,
                "content": f"[{publisher}] {title}\n\n{body}",
                "source_url": url,
            }
        )

    if not rows:
        logger.info("No STORY-type news found for %s", ticker)
        return 0

    # Upsert by ticker + date + title (use title hash as part of uniqueness)
    # Since documents table doesn't have a unique constraint on news,
    # we check for existing titles to avoid duplicates
    for row in rows:
        existing = await db.execute(
            Document.__table__.select().where(
                Document.ticker == row["ticker"],
                Document.doc_type == "news",
                Document.title == row["title"],
            )
        )
        if existing.first() is None:
            db.add(Document(**row))

    await db.commit()

    logger.info("Stored %d news articles for %s", len(rows), ticker)
    return len(rows)
