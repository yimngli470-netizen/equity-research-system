"""Portfolio model (roadmap 6.2) — the actual book the sizing engine reasons about.

Until now position sizing produced an *abstract* target weight and faked its concentration input
(a count of same-sector watchlist names). This is the real holdings ledger: what you own (shares +
cost basis) plus a cash balance, so weights are honest fractions of the WHOLE book and the decision
can say "add 2%" against what you actually hold — not just "target 5%".

Manual CRUD only — no brokerage integration (consistent with the free-data, local-first stance).
Single personal portfolio: one `PortfolioAccount` row (the cash side), many `PortfolioPosition` rows.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True, index=True)  # one row per name
    shares: Mapped[float] = mapped_column(Float)
    cost_basis: Mapped[float | None] = mapped_column(Float)   # average cost per share (for P&L)
    opened_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PortfolioAccount(Base):
    """The cash side of the book — a singleton (id=1). Tracked explicitly so weights are fractions of
    total capital (a 100%-cash book sizes adds correctly; an under-invested book isn't distorted)."""

    __tablename__ = "portfolio_account"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cash: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    label: Mapped[str | None] = mapped_column(String(100))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
