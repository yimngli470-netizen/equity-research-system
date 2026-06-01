"""Shared test fixtures.

DB strategy (per ANALYST_ROADMAP §Testing): an ephemeral Postgres via **testcontainers** by
default (isolated, great for CI). For fast local runs you can point at an existing throwaway DB
with `TEST_DATABASE_URL=postgresql+asyncpg://user:pw@host/equity_research_test pytest`.

Isolation: the schema is created once per session (`Base.metadata.create_all` — the models are the
source of truth; the `vector` extension is enabled for the pgvector column on `documents`). Each
test starts from a clean slate via TRUNCATE … CASCADE, so code-under-test that commits is fine.

No test hits the network or the real Anthropic API — LLM calls are mocked (see `mock_anthropic`).
"""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import every model so Base.metadata is fully populated before create_all.
import app.models  # noqa: F401
from app.database import Base


@pytest.fixture(scope="session")
def db_url() -> AsyncIterator[str]:
    """asyncpg URL for the test database — env override, else an ephemeral testcontainer."""
    override = os.getenv("TEST_DATABASE_URL")
    if override:
        yield override
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
        yield pg.get_connection_url()


# The schema is created once per process. The engine itself is function-scoped so it lives on the
# same event loop as the test using it — sharing a session-scoped asyncpg engine across pytest's
# per-test loops triggers "another operation is in progress".
_SCHEMA_READY = False


@pytest_asyncio.fixture
async def engine(db_url):
    """Function-scoped engine. Creates the schema once (idempotent), then truncates per test."""
    global _SCHEMA_READY
    eng = create_async_engine(db_url, echo=False)
    if not _SCHEMA_READY:
        async with eng.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        _SCHEMA_READY = True

    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with eng.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncIterator[AsyncSession]:
    """A clean DB session per test (the engine fixture already truncated)."""
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def client(engine) -> AsyncIterator["object"]:
    """httpx AsyncClient bound to the FastAPI app, with get_db overridden onto the test engine."""
    import httpx

    from app.database import get_db
    from app.main import app

    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db():
        async with sessionmaker() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_anthropic(monkeypatch):
    """Patch anthropic.Anthropic with a fake whose response text is set per test.

    Returns a setter `set_response(text)` and records the last (system, user) prompt so tests can
    assert on what the model was actually asked (e.g. that the grounding numbers were included).
    """
    state: dict = {"response": "{}", "system": None, "user": None}

    class _Msg:
        def __init__(self, text):
            self.content = [type("C", (), {"text": text})()]

    class _Messages:
        def create(self, *, model, max_tokens, system, messages, **kw):
            state["system"] = system
            state["user"] = messages[-1]["content"] if messages else None
            return _Msg(state["response"])

    class _FakeAnthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)

    class Handle:
        def set_response(self, text):
            state["response"] = text

        @property
        def last_system(self):
            return state["system"]

        @property
        def last_user(self):
            return state["user"]

    return Handle()


# ── seed helpers ──────────────────────────────────────────────────────────────

async def seed_stock(db: AsyncSession, ticker: str, **kw):
    from app.models.stock import Stock
    s = Stock(ticker=ticker, name=kw.pop("name", ticker), active=kw.pop("active", True), **kw)
    db.add(s)
    await db.commit()
    return s


async def seed_valuation(db: AsyncSession, ticker: str, on_date, **multiples):
    from app.models.valuation import Valuation
    db.add(Valuation(ticker=ticker, date=on_date, **multiples))
    await db.commit()


async def seed_score(db: AsyncSession, ticker: str, on_date, composite: float, signal: str, **cats):
    from app.models.score import StockScore
    base = dict(growth_score=0.5, profitability_score=0.5, valuation_score=0.5,
                momentum_score=0.5, sentiment_score=0.5, risk_score=0.5, event_score=0.5)
    base.update(cats)
    db.add(StockScore(ticker=ticker, date=on_date, composite_score=composite, signal=signal, **base))
    await db.commit()


async def seed_peer_weight(db: AsyncSession, ticker: str, peer: str, weight: float, **kw):
    from app.models.peer import PeerWeight
    db.add(PeerWeight(ticker=ticker, peer=peer, weight=weight, **kw))
    await db.commit()


async def seed_financials(
    db: AsyncSession, ticker: str, *, n: int = 12, revenue: float = 1000.0,
    gross_margin: float = 0.5, op_margin: float = 0.2, net_margin: float = 0.15,
    ocf: float = 200.0, fcf: float = 150.0,
):
    """n constant quarters — enough for compute_quant_profile (>= MIN_QUARTERS)."""
    from datetime import date, timedelta

    from app.models.financial import Financial
    end = date(2023, 3, 31)
    for i in range(n):
        pe = end + timedelta(days=91 * i)
        db.add(Financial(
            ticker=ticker, period=f"Q{i % 4 + 1} {pe.year}", period_end_date=pe,
            revenue=revenue, gross_profit=revenue * gross_margin,
            operating_income=revenue * op_margin, net_income=revenue * net_margin,
            operating_cash_flow=ocf, free_cash_flow=fcf, source="test",
        ))
    await db.commit()


async def seed_prices(db: AsyncSession, ticker: str, closes: list[float]):
    from datetime import date, timedelta

    from app.models.price import DailyPrice
    start = date(2024, 1, 1)
    for i, px in enumerate(closes):
        d = start + timedelta(days=i)
        db.add(DailyPrice(ticker=ticker, date=d, open=px, high=px, low=px,
                          close=px, adj_close=px, volume=1000))
    await db.commit()
