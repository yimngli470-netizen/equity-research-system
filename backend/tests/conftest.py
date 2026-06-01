"""Shared test fixtures for the end-to-end pipeline test.

DB strategy: an ephemeral Postgres via **testcontainers** by default (isolated, CI-friendly). For
fast local runs, point at a throwaway DB with
`TEST_DATABASE_URL=postgresql+asyncpg://user:pw@host/equity_research_test pytest`.

The schema is created once per session from the models (the `vector` extension is enabled for the
pgvector column on `documents`); each test starts clean via TRUNCATE … CASCADE. No test hits the
network or the real Anthropic API — the e2e test mocks every external boundary itself.
"""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  — populate Base.metadata before create_all
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


# Schema is created once per process; the engine is function-scoped so it lives on the same event
# loop as the test using it (a session-scoped asyncpg engine across pytest's per-test loops raises
# "another operation is in progress").
_SCHEMA_READY = False


@pytest_asyncio.fixture
async def engine(db_url):
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
    """httpx AsyncClient bound to the FastAPI app, with get_db pointed at the test engine."""
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


async def seed_stock(db: AsyncSession, ticker: str, **kw):
    from app.models.stock import Stock
    s = Stock(ticker=ticker, name=kw.pop("name", ticker), active=kw.pop("active", True), **kw)
    db.add(s)
    await db.commit()
    return s
