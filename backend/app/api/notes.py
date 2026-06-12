"""Research-note API (roadmap 5.1) — fetch/build the professional deliverable."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.research_note import ResearchNote
from app.notes.builder import build_research_note

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteResponse(BaseModel):
    ticker: str
    as_of: str
    note_md: str
    changes: list[str] | None = None


class NoteBuildRequest(BaseModel):
    ticker: str


def _resp(row: ResearchNote) -> NoteResponse:
    return NoteResponse(ticker=row.ticker, as_of=str(row.as_of), note_md=row.note_md,
                        changes=row.changes)


@router.post("/build", response_model=NoteResponse)
async def build_note(req: NoteBuildRequest, db: AsyncSession = Depends(get_db)):
    """Rebuild today's note from current artifacts (deterministic, no LLM)."""
    row = await build_research_note(db, req.ticker.upper())
    if row is None:
        raise HTTPException(status_code=400, detail="No decision yet — run the pipeline first.")
    return _resp(row)


@router.get("/{ticker}/latest", response_model=NoteResponse | None)
async def latest_note(ticker: str, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(ResearchNote).where(ResearchNote.ticker == ticker.upper())
            .order_by(ResearchNote.as_of.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return _resp(row) if row else None


@router.get("/{ticker}/history")
async def note_history(ticker: str, db: AsyncSession = Depends(get_db)):
    """Dated list of past notes (for the archive view)."""
    rows = (
        await db.execute(
            select(ResearchNote.as_of, ResearchNote.changes)
            .where(ResearchNote.ticker == ticker.upper())
            .order_by(ResearchNote.as_of.desc()).limit(50)
        )
    ).all()
    return [{"as_of": str(r.as_of), "changes": r.changes} for r in rows]
