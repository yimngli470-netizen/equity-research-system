from datetime import date

from sqlalchemy import BigInteger, Date, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PeerWeight(Base):
    """Measured closeness of `peer` to `ticker` (roadmap 1.2).

    One row per ordered (ticker, peer) pair. `weight` is a 0–1 blended closeness — the input to
    peer-relative normalization (1.3): instead of one absolute ruler, a metric is scored against
    its weighted peers. The weight is *measured*, not LLM-opined: a blend of standardized
    fundamental-feature distance and trailing return correlation (and, once ML M1 lands, business-
    description embedding cosine). Components are stored so the blend is auditable.
    """

    __tablename__ = "peer_weights"
    __table_args__ = (UniqueConstraint("ticker", "peer", name="uq_peer_ticker_peer"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    peer: Mapped[str] = mapped_column(String(10), index=True)

    weight: Mapped[float] = mapped_column(Float)                    # blended closeness, 0–1
    fundamental_sim: Mapped[float | None] = mapped_column(Float)    # 0–1, from quant-profile distance
    return_corr: Mapped[float | None] = mapped_column(Float)        # raw Pearson, -1..1
    embedding_sim: Mapped[float | None] = mapped_column(Float)      # 0–1, 10-K desc cosine (M1; null for now)

    as_of: Mapped[date | None] = mapped_column(Date)
