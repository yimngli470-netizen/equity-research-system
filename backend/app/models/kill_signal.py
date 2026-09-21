"""Standing per-ticker KILL SIGNALS — the conditions that would break the thesis.

Sibling to `TickerKeyMetric`: key metrics are what to WATCH each quarter, kill signals are what
would make you SELL. Both are per-ticker, hand-curatable, and long-lived.

Distinct from `StockThesis.kill_criteria`, which is an *immutable per-run snapshot* of what the
judge predicted on one date and is graded later by `thesis/grading.py`. That record must never be
edited — it is the accountability log. This table is the opposite: a living watchlist the user
owns. The two are connected in one direction only — after a judge run, its kill_criteria are
offered here as `candidate` rows for the user to accept, edit, or dismiss. Accepting copies the
text; it never mutates the thesis.

Statuses:
  candidate — proposed by the judge, awaiting review (invisible to the agent context)
  active    — the user's standing list; fed to the judge so it doesn't re-propose them
  tripped   — fired. Set automatically by kill_signals/evaluator.py when it finds the condition
              met in the reported quarter, with the evidence recorded on KillSignalEvaluation.
              Never un-set automatically — a signal that fired is a decision event, and only the
              user clears it.
  dismissed — rejected. Retained (not deleted) so the same judge proposal is not re-offered
              every run; the unique constraint on (ticker, signal) is what makes that work.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class TickerKillSignal(Base):
    __tablename__ = "ticker_kill_signals"
    __table_args__ = (
        UniqueConstraint("ticker", "signal", name="uq_kill_signal_ticker_signal"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)

    # The falsifiable condition itself, e.g. "HBM ASPs decline QoQ for two consecutive quarters".
    # Text, not String(n): a judge kill-criterion is a full falsifiable sentence and
    # truncating it would destroy the claim it makes.
    signal: Mapped[str] = mapped_column(Text)
    # Why this breaks the thesis — the reasoning, kept separate so the signal stays scannable.
    rationale: Mapped[str | None] = mapped_column(Text)

    source: Mapped[str] = mapped_column(String(10), server_default="manual")  # llm | manual | judge
    severity: Mapped[str] = mapped_column(String(10), server_default="high")  # critical | high | medium
    status: Mapped[str] = mapped_column(String(10), server_default="active", index=True)

    # Judge kill-criteria carry a resolution date; manual signals usually don't.
    by_date: Mapped[date | None] = mapped_column(Date)
    # Which thesis snapshot this candidate came from — provenance back to the judge run.
    origin_as_of: Mapped[date | None] = mapped_column(Date)

    tripped_on: Mapped[date | None] = mapped_column(Date)
    tripped_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KillSignalEvaluation(Base):
    """Per-quarter verdict on ONE kill signal — did this condition happen?

    Same shape and discipline as `TickerKpiValue`: one row per (signal, period), a verbatim
    evidence quote, explicit provenance, and "undetermined" as a valid honest answer rather than
    a guess. Keeping the history (instead of only stamping the signal) means you can see that a
    condition was checked and found NOT met in Q1 and Q2 before it tripped in Q3 — which is the
    difference between a tripwire and an assertion.
    """

    __tablename__ = "kill_signal_evaluations"
    __table_args__ = (
        UniqueConstraint("signal_id", "period_end_date", name="uq_kill_eval_signal_period"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ticker_kill_signals.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    period_end_date: Mapped[date] = mapped_column(Date, index=True)

    # tripped | approaching | not_tripped | undetermined
    verdict: Mapped[str] = mapped_column(String(20))
    # Verbatim span from the source that establishes the verdict (null when undetermined).
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(20))     # transcript | financials | unknown
    source_url: Mapped[str | None] = mapped_column(String(300))
    as_of: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
