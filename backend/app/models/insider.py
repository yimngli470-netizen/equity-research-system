from datetime import date

from sqlalchemy import BigInteger, Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InsiderTrade(Base):
    __tablename__ = "insider_trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    insider_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200))
    trade_type: Mapped[str] = mapped_column(String(20))  # 'buy', 'sell'
    shares: Mapped[int] = mapped_column(Integer)
    price: Mapped[float | None] = mapped_column(Float)
