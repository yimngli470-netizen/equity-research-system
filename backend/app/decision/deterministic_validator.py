"""Deterministic claim validation (Phase 6-lite of AI_REPORTING_IMPROVEMENT_PLAN).

The principle: code owns facts, AI owns interpretation.

Today the validation agent uses an LLM to do arithmetic ("does the claim 18.5%
match the DB value 18.6%?"). That's the wrong tool — LLMs are unreliable at
math and waste tokens. This module does numeric/date/multiple verification
in pure Python with explicit tolerance bands. The LLM validator stays for
softer checks (tone fairness, reasoning quality).

Approach: walk every string field in every agent report, run regex patterns
to extract numeric claims with their context, then compare each against the
canonical DB value with documented tolerances.
"""

import logging
import re
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import Financial
from app.models.price import DailyPrice
from app.models.valuation import Valuation

logger = logging.getLogger(__name__)


# Tolerance bands — match what the LLM validator's system prompt enforces,
# but applied deterministically here so we never regress.
TOL_MULTIPLE = 0.1     # ±0.1x for P/E, P/S, EV/EBITDA, PEG
TOL_PCT_REL = 0.05     # ±5% relative for "CLOSE" verdict
TOL_DOLLAR_REL = 0.01  # ±1% relative for dollar amounts → CONFIRMED


@dataclass
class DeterministicCheck:
    agent: str           # which agent's report contained the claim
    claim: str           # excerpt of the matched text
    field: str           # canonical field name (e.g. "forward_pe", "revenue_2026Q1")
    expected_value: float | None  # what the agent claimed
    actual_value: float | None    # what the DB says
    tolerance: str       # human-readable description
    verdict: str         # CONFIRMED | CLOSE | CONTRADICTED | UNVERIFIABLE
    detail: str
    source: str = "deterministic"

    def to_dict(self) -> dict:
        return asdict(self)


# ────────────────────────────────────────────────────────────────────────────
# Regex patterns
# ────────────────────────────────────────────────────────────────────────────

# Multiples: "Forward P/E of 16.8x", "trailing P/E 22.2"
_RE_FORWARD_PE = re.compile(r"forward[\s-]*p\/?e\s+(?:of|at|is|=)?\s*(\d+\.?\d*)\s*x?", re.IGNORECASE)
_RE_TRAILING_PE = re.compile(r"trailing[\s-]*p\/?e\s+(?:of|at|is|=)?\s*(\d+\.?\d*)\s*x?", re.IGNORECASE)
_RE_PS = re.compile(r"\bp\/?s(?:\s+ratio)?\s+(?:of|at|is|=)?\s*(\d+\.?\d*)\s*x?", re.IGNORECASE)
_RE_EV_EBITDA = re.compile(r"ev\/?ebitda\s+(?:of|at|is|=)?\s*(\d+\.?\d*)\s*x?", re.IGNORECASE)
_RE_PEG = re.compile(r"\bpeg(?:\s+ratio)?\s+(?:of|at|is|=)?\s*(\d+\.?\d*)", re.IGNORECASE)

# Quarter-specific: "Q1 2026 revenue of $56.31B" / "Q1 2026 revenue grew to $56.3B"
# Captures (quarter, year, amount, unit)
_RE_Q_REVENUE = re.compile(
    r"q([1-4])\s*(\d{4})\s+revenue\s+(?:of|at|was|reached|grew\s+to|rose\s+to)?\s*\$?(\d+\.?\d*)\s*([bmt])\b",
    re.IGNORECASE,
)
# "Q1 2026 EPS of $10.44"
_RE_Q_EPS = re.compile(
    r"q([1-4])\s*(\d{4})\s+(?:diluted\s+)?eps\s+(?:of|at|was|reached)?\s*\$?(\d+\.?\d*)",
    re.IGNORECASE,
)

# Current/latest price: "current price 671.58" or "current price of $608.74"
_RE_CURRENT_PRICE = re.compile(
    r"current\s+price\s+(?:of\s+|is\s+|at\s+)?\$?(\d+\.?\d*)",
    re.IGNORECASE,
)


# ────────────────────────────────────────────────────────────────────────────
# Core validator
# ────────────────────────────────────────────────────────────────────────────


class DeterministicValidator:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker
        self.financials_by_period: dict[str, Financial] = {}
        self.valuation: Valuation | None = None
        self.latest_price: DailyPrice | None = None
        self.checks: list[DeterministicCheck] = []
        self._seen_keys: set[tuple[str, str, str]] = set()  # dedupe identical claims

    async def load_facts(self) -> None:
        """Cache canonical values for the comparison window."""
        result = await self.db.execute(
            select(Financial)
            .where(Financial.ticker == self.ticker)
            .order_by(Financial.period_end_date.desc())
            .limit(8)
        )
        for f in result.scalars().all():
            q = (f.period_end_date.month - 1) // 3 + 1
            self.financials_by_period[f"{f.period_end_date.year}Q{q}"] = f

        val_res = await self.db.execute(
            select(Valuation)
            .where(Valuation.ticker == self.ticker)
            .order_by(Valuation.date.desc())
            .limit(1)
        )
        self.valuation = val_res.scalar_one_or_none()

        price_res = await self.db.execute(
            select(DailyPrice)
            .where(DailyPrice.ticker == self.ticker)
            .order_by(DailyPrice.date.desc())
            .limit(1)
        )
        self.latest_price = price_res.scalar_one_or_none()

    # ── Walking agent reports ───────────────────────────────────────────────

    def _walk_strings(self, obj, path=""):
        """Yield (path, string) for every string field recursively."""
        if isinstance(obj, str):
            if len(obj) >= 20:  # ignore tiny labels and enum-like values
                yield path, obj
        elif isinstance(obj, dict):
            for k, v in obj.items():
                yield from self._walk_strings(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from self._walk_strings(v, f"{path}[{i}]")

    def check_all(self, reports: dict[str, dict]) -> list[DeterministicCheck]:
        """Run all pattern checks across every agent's report."""
        for agent, report in reports.items():
            if agent == "validation":
                continue  # never validate the validator's own claims
            if not isinstance(report, dict) or "error" in report:
                continue
            for path, text in self._walk_strings(report):
                self._check_multiples(text, agent)
                self._check_quarterly_revenue(text, agent)
                self._check_quarterly_eps(text, agent)
                self._check_current_price(text, agent)
        return self.checks

    # ── Pattern checks ──────────────────────────────────────────────────────

    def _check_multiples(self, text: str, agent: str) -> None:
        if not self.valuation:
            return
        v = self.valuation
        for regex, field, actual in (
            (_RE_FORWARD_PE, "forward_pe", v.forward_pe),
            (_RE_TRAILING_PE, "trailing_pe", v.trailing_pe),
            (_RE_PS, "price_to_sales", v.price_to_sales),
            (_RE_EV_EBITDA, "ev_to_ebitda", v.ev_to_ebitda),
            (_RE_PEG, "peg_ratio", v.peg_ratio),
        ):
            if actual is None:
                continue
            for m in regex.finditer(text):
                claimed = self._safe_float(m.group(1))
                if claimed is None or claimed > 1000:
                    # Skip implausibly large numbers (likely mismatched)
                    continue
                self._compare_multiple(claimed, actual, field, agent, m.group(0))

    def _check_quarterly_revenue(self, text: str, agent: str) -> None:
        for m in _RE_Q_REVENUE.finditer(text):
            q, y, amount, unit = m.group(1), m.group(2), m.group(3), m.group(4).upper()
            key = f"{y}Q{q}"
            fin = self.financials_by_period.get(key)
            if fin is None or fin.revenue is None:
                continue

            multiplier = {"B": 1e9, "M": 1e6, "T": 1e12}[unit]
            claimed_dollars = self._safe_float(amount)
            if claimed_dollars is None:
                continue
            claimed_dollars *= multiplier

            self._compare_dollar(
                claimed_dollars, fin.revenue,
                field=f"revenue_{key}",
                agent=agent, claim_text=m.group(0),
            )

    def _check_quarterly_eps(self, text: str, agent: str) -> None:
        for m in _RE_Q_EPS.finditer(text):
            q, y, amount = m.group(1), m.group(2), m.group(3)
            key = f"{y}Q{q}"
            fin = self.financials_by_period.get(key)
            if fin is None or fin.eps is None:
                continue

            claimed = self._safe_float(amount)
            if claimed is None:
                continue
            self._compare_dollar(
                claimed, fin.eps,
                field=f"eps_{key}",
                agent=agent, claim_text=m.group(0),
                # EPS dollar amounts are small — use ±$0.05 absolute tolerance
                # in addition to relative.
                absolute_tolerance=0.05,
            )

    def _check_current_price(self, text: str, agent: str) -> None:
        if not self.latest_price:
            return
        for m in _RE_CURRENT_PRICE.finditer(text):
            claimed = self._safe_float(m.group(1))
            if claimed is None:
                continue
            self._compare_dollar(
                claimed, self.latest_price.close,
                field="current_price",
                agent=agent, claim_text=m.group(0),
                absolute_tolerance=0.50,
            )

    # ── Comparison helpers ──────────────────────────────────────────────────

    def _compare_multiple(self, claimed, actual, field, agent, claim_text):
        diff = abs(claimed - actual)
        rel = diff / actual if actual else float("inf")
        if diff <= TOL_MULTIPLE:
            verdict, detail = "CONFIRMED", f"Within ±{TOL_MULTIPLE}x of DB {actual:.2f}x"
        elif rel <= TOL_PCT_REL:
            verdict, detail = "CLOSE", f"Within {TOL_PCT_REL:.0%} of DB {actual:.2f}x"
        else:
            verdict, detail = (
                "CONTRADICTED",
                f"Differs from DB {actual:.2f}x by {diff:.2f}x ({rel:.1%})",
            )
        self._add_check(agent, claim_text, field, claimed, actual, f"±{TOL_MULTIPLE}x", verdict, detail)

    def _compare_dollar(self, claimed, actual, field, agent, claim_text, absolute_tolerance: float | None = None):
        diff = abs(claimed - actual)
        rel = diff / abs(actual) if actual else float("inf")

        within_abs = absolute_tolerance is not None and diff <= absolute_tolerance
        if within_abs or rel <= TOL_DOLLAR_REL:
            verdict = "CONFIRMED"
            detail = f"Within tolerance of DB {actual:,.2f}"
        elif rel <= TOL_PCT_REL:
            verdict = "CLOSE"
            detail = f"Within {rel:.1%} of DB {actual:,.2f}"
        else:
            verdict = "CONTRADICTED"
            detail = f"Claim {claimed:,.2f} differs from DB {actual:,.2f} by {rel:.1%}"

        tol_str = f"±{absolute_tolerance}" if absolute_tolerance else f"±{TOL_DOLLAR_REL:.0%}"
        self._add_check(agent, claim_text, field, claimed, actual, tol_str, verdict, detail)

    def _add_check(self, agent, claim, field, expected, actual, tolerance, verdict, detail):
        # Dedupe: same agent + field + (rounded) value collapses to one check
        key = (agent, field, f"{expected:.4f}" if expected is not None else "")
        if key in self._seen_keys:
            return
        self._seen_keys.add(key)
        self.checks.append(DeterministicCheck(
            agent=agent,
            claim=claim.strip(),
            field=field,
            expected_value=expected,
            actual_value=actual,
            tolerance=tolerance,
            verdict=verdict,
            detail=detail,
        ))

    @staticmethod
    def _safe_float(s: str) -> float | None:
        try:
            return float(s)
        except (ValueError, TypeError):
            return None


async def run_deterministic_validation(
    db: AsyncSession,
    ticker: str,
    agent_reports: dict[str, dict],
) -> list[DeterministicCheck]:
    """Convenience wrapper: load facts, run checks, return list."""
    v = DeterministicValidator(db, ticker)
    await v.load_facts()
    return v.check_all(agent_reports)
