"""Server-side Run All — runs the full pipeline for every active ticker in a background task with a
bounded worker pool, so the sequence survives the browser. The old Run All looped in the browser
(`pipelineTracker.ts`), which meant a single dropped/stuck client request silently stalled the whole
watchlist (and closing the tab killed it). Here the always-on backend container owns the loop; the
dashboard just kicks it off and polls status.

State is in-memory — this is a single-user personal system and only one Run All runs at a time. A
fresh run replaces the previous run's final state. The bounded pool (default 3) exists because in
dev every LLM call goes through the Claude CLI on the user's subscription, which shares a 5-hour
rate limit; firing the whole watchlist at once trips it.
"""

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.orchestrator import run_all_agents
from app.database import async_session
from app.decision.engine import run_decision
from app.ingestion.pipeline import ingest_ticker
from app.models.stock import Stock
from app.scoring.calculator import calculate_score

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 3
MAX_CONCURRENCY = 6


@dataclass
class TickerOutcome:
    ticker: str
    ok: bool
    error: str | None = None
    usage_limited: bool = False


@dataclass
class RunAllState:
    running: bool = False
    total: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    in_flight: list[str] = field(default_factory=list)
    done: list[TickerOutcome] = field(default_factory=list)
    stopped_reason: str | None = None  # "usage_limit" when we halt the pool early

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "total": self.total,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "in_flight": list(self.in_flight),
            "done": [asdict(o) for o in self.done],
            "done_count": len(self.done),
            "stopped_reason": self.stopped_reason,
        }


_state = RunAllState()
_task: asyncio.Task | None = None
_lock = asyncio.Lock()


async def _run_one(ticker: str) -> TickerOutcome:
    """Full chain for one ticker: ingest → agents (smart) → score → decision. Mirrors the
    per-ticker `runPipeline` the frontend used to drive. Never raises — one bad ticker must not
    kill the pool."""
    try:
        await ingest_ticker(ticker)
        agent_result = await run_all_agents(ticker=ticker, mode="smart")
        failures = [r for r in agent_result.results if not r.success]
        if failures:
            usage_limited = any(r.usage_limited for r in failures)
            detail = " · ".join(
                f"{r.agent_type}{f': {r.error}' if r.error else ''}" for r in failures
            )
            return TickerOutcome(
                ticker=ticker,
                ok=False,
                error="subscription usage limit hit — re-run later to resume" if usage_limited else detail,
                usage_limited=usage_limited,
            )
        async with async_session() as db:
            await calculate_score(db, ticker)
            await run_decision(db, ticker)
        return TickerOutcome(ticker=ticker, ok=True)
    except Exception as e:  # noqa: BLE001 — isolate the pool from any single-ticker failure
        logger.exception("[run-all] %s failed", ticker)
        return TickerOutcome(ticker=ticker, ok=False, error=str(e))


async def _run_all(tickers: list[str], concurrency: int) -> None:
    next_idx = 0
    stop = False

    async def worker() -> None:
        nonlocal next_idx, stop
        while not stop:
            i = next_idx  # no await between read and increment ⇒ each worker gets a unique index
            next_idx += 1
            if i >= len(tickers):
                return
            ticker = tickers[i]
            _state.in_flight.append(ticker)
            outcome = await _run_one(ticker)
            if ticker in _state.in_flight:
                _state.in_flight.remove(ticker)
            _state.done.append(outcome)
            if outcome.usage_limited:
                # No point launching more — they'd all fail the same way. Smart-cache resumes cheaply.
                stop = True
                _state.stopped_reason = "usage_limit"

    try:
        await asyncio.gather(*[worker() for _ in range(min(concurrency, len(tickers)))])
    finally:
        _state.running = False
        _state.in_flight = []
        _state.finished_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "[run-all] finished: %d/%d ok, stopped_reason=%s",
            sum(1 for o in _state.done if o.ok),
            _state.total,
            _state.stopped_reason,
        )


async def start_run_all(concurrency: int = DEFAULT_CONCURRENCY) -> dict:
    """Kick off a background Run All over all active tickers. If one is already running, this is a
    no-op that just returns the live state (so a double-click / reopened tab attaches instead of
    starting a second run)."""
    global _task, _state
    async with _lock:
        if _state.running:
            return _state.snapshot()
        async with async_session() as db:
            tickers = (
                await db.execute(
                    select(Stock.ticker).where(Stock.active.is_(True)).order_by(Stock.ticker)
                )
            ).scalars().all()
        _state = RunAllState(
            running=True,
            total=len(tickers),
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        concurrency = max(1, min(concurrency, MAX_CONCURRENCY))
        _task = asyncio.create_task(_run_all(list(tickers), concurrency))
        logger.info("[run-all] started: %d tickers, concurrency=%d", len(tickers), concurrency)
        return _state.snapshot()


def get_run_all_status() -> dict:
    return _state.snapshot()
