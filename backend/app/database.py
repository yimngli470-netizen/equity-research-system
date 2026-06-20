from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# echo is OFF by default — it logs every SQL statement with all bound parameters (a single KPI/price
# upsert is a multi-KB line that floods docker logs). Turn it on only when debugging SQL: DB_ECHO=true.
engine = create_async_engine(settings.database_url, echo=settings.db_echo)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
