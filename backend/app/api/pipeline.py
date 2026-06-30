"""Pipeline API — server-side Run All (background task + status polling).

The loop runs in the backend (see app/pipeline/runner.py) so it survives the browser: start it,
then poll status. Closing the tab no longer stalls the watchlist run.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.pipeline.runner import DEFAULT_CONCURRENCY, get_run_all_status, start_run_all

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class RunAllRequest(BaseModel):
    concurrency: int = DEFAULT_CONCURRENCY


@router.post("/run-all")
async def run_all(request: RunAllRequest | None = None):
    """Start a background Run All over every active ticker. No-op (returns live state) if one is
    already running."""
    concurrency = request.concurrency if request else DEFAULT_CONCURRENCY
    return await start_run_all(concurrency=concurrency)


@router.get("/run-all/status")
async def run_all_status():
    """Current Run All progress — for the dashboard to poll."""
    return get_run_all_status()
