"""SEC EDGAR XBRL ingester — authoritative quarterly financials from filed 10-Q/10-K.

This is the planned source-of-truth for the `financials` table (ANALYST_ROADMAP.md item
0.1/0.2). yfinance gives ~6 shallow quarters; EDGAR `companyfacts` gives the full filed
history with real fiscal-period labels, and every number traces to an SEC filing (the
verifiability spine the long-term analyst needs).

This module currently EXTRACTS + RECONCILES only — it does not yet write to the DB. The
replace-vs-alongside decision (roadmap open decision #1) is made after we see MU reconcile.

Real-world XBRL gotchas handled here:
  * Tag evolution — revenue is filed as SalesRevenueNet (pre-2018) then
    RevenueFromContractWithCustomerExcludingAssessedTax (ASC 606). The concept→tag map
    stitches them in priority order.
  * Income statement files discrete 3-month (~90d) contexts → used directly per quarter.
  * Fiscal Q4 is usually only in the annual 10-K (no standalone 10-Q) → derived as
    FY − (Q1+Q2+Q3).
  * Cash-flow statements are cumulative YTD → standalone quarter = YTD(n) − YTD(n-1).
  * Balance-sheet items are point-in-time (instant) → taken by period-end date.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

import httpx
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import Financial

logger = logging.getLogger(__name__)

# SEC fair-access policy requires a descriptive User-Agent with contact info.
SEC_UA = "equity-research-system personal-use yimngli470@gmail.com"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Canonical concept -> ordered candidate us-gaap tags (first match per period wins).
CONCEPT_TAGS: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "cost_of_revenue": ["CostOfGoodsAndServicesSold", "CostOfRevenue"],
    "gross_profit": ["GrossProfit"],  # else derived: revenue - cost_of_revenue
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "eps": ["EarningsPerShareDiluted"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    # balance sheet (instant)
    "total_assets": ["Assets"],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    # debt components (instant; composed into total_debt — roadmap 4.1)
    "debt_lt_noncurrent": ["LongTermDebtNoncurrent"],
    "debt_lt_current": ["LongTermDebtCurrent"],
    "debt_lt_total": ["LongTermDebt"],  # fallback when the nc/current split isn't filed
    "debt_st_borrowings": ["ShortTermBorrowings", "CommercialPaper"],
    # share counts (roadmap 4.1 — dilution awareness for the forecast model)
    "shares_outstanding_instant": ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
    "shares_diluted_wavg": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    # capital-return / dilution flows (cumulative YTD, like cash flow)
    "stock_based_comp": ["ShareBasedCompensation"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
}

_QTR_ORDER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}


@dataclass
class EdgarQuarter:
    """One fiscal quarter assembled from filed XBRL facts."""

    fy: int
    fp: str  # Q1..Q4
    period_end_date: date
    filed_date: date | None = None  # earliest SEC filing reporting this period (M4 gating)
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    eps: float | None = None
    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    total_assets: float | None = None
    total_equity: float | None = None
    cash_and_equivalents: float | None = None
    total_debt: float | None = None
    shares_outstanding: float | None = None
    stock_based_comp: float | None = None
    buybacks: float | None = None
    derived: list[str] = field(default_factory=list)  # which fields were computed, not filed

    @property
    def label(self) -> str:
        return f"{self.fp} FY{self.fy}"


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _get_json(url: str) -> dict:
    with httpx.Client(headers={"User-Agent": SEC_UA}, timeout=30.0) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


@lru_cache(maxsize=1)
def _ticker_map() -> dict[str, int]:
    """{TICKER: cik} from the official SEC map, fetched once per process."""
    data = _get_json(TICKERS_URL)
    return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}


def get_cik(ticker: str) -> int | None:
    """Resolve a ticker to its SEC CIK via the official map."""
    return _ticker_map().get(ticker.upper())


def fetch_companyfacts(cik: int) -> dict:
    time.sleep(0.2)  # be polite (SEC asks <=10 req/s)
    return _get_json(FACTS_URL.format(cik=cik))


# ── fact parsing ───────────────────────────────────────────────────────────────

def _dur_days(rec: dict) -> int | None:
    if not rec.get("start") or not rec.get("end"):
        return None
    return (date.fromisoformat(rec["end"]) - date.fromisoformat(rec["start"])).days


def _concept_facts(facts: dict, concept: str, unit: str) -> list[dict]:
    """All facts for a concept across its candidate tags, tagged with priority rank."""
    out: list[dict] = []
    gaap = facts.get("us-gaap", {})
    for rank, tag in enumerate(CONCEPT_TAGS[concept]):
        node = gaap.get(tag)
        if not node:
            continue
        for rec in node.get("units", {}).get(unit, []):
            out.append({**rec, "_rank": rank})
    return out


def _pick(records: list[dict]) -> dict:
    """Among duplicate facts for the same period, prefer the most recently filed
    (handles restatements), then the highest-priority (lowest-rank) tag."""
    return sorted(records, key=lambda r: (r.get("filed", ""), -r["_rank"]))[-1]


def _three_month_map(records: list[dict]) -> dict[tuple[int, str], dict]:
    """{(fy, fp): rec} for discrete ~3-month quarterly facts (Q1-Q3, sometimes Q4)."""
    buckets: dict[tuple[int, str], list[dict]] = {}
    for r in records:
        d = _dur_days(r)
        if d is None or not (80 <= d <= 100):
            continue
        fp, fy = r.get("fp"), r.get("fy")
        if fp not in _QTR_ORDER or fy is None:
            continue
        buckets.setdefault((fy, fp), []).append(r)
    return {k: _pick(v) for k, v in buckets.items()}


def _annual_map(records: list[dict]) -> dict[int, dict]:
    """{fy: rec} for full-year (~365d, fp=FY) facts — used to derive Q4."""
    buckets: dict[int, list[dict]] = {}
    for r in records:
        d = _dur_days(r)
        if d is None or not (350 <= d <= 380) or r.get("fp") != "FY":
            continue
        buckets.setdefault(r["fy"], []).append(r)
    return {k: _pick(v) for k, v in buckets.items()}


def _ytd_standalone(records: list[dict]) -> dict[tuple[int, str], dict]:
    """Cash-flow concepts file cumulative YTD. Recover standalone quarters by differencing
    consecutive YTD values within a fiscal year."""
    # cumulative YTD value per (fy, fp), identified by duration band
    bands = {"Q1": (80, 100), "Q2": (170, 195), "Q3": (260, 285), "FY": (350, 380)}
    ytd: dict[tuple[int, str], dict] = {}
    for r in records:
        d, fy = _dur_days(r), r.get("fy")
        if d is None or fy is None:
            continue
        for fp, (lo, hi) in bands.items():
            if lo <= d <= hi:
                ytd.setdefault((fy, fp), []).append({**r, "_fp": fp})
    picked = {k: _pick(v) for k, v in ytd.items()}

    out: dict[tuple[int, str], dict] = {}
    for fy in {k[0] for k in picked}:
        prev = 0.0
        for fp in ("Q1", "Q2", "Q3", "FY"):
            rec = picked.get((fy, fp))
            if rec is None:
                prev = None  # gap breaks the chain
                continue
            if prev is None:
                prev = rec["val"]
                continue
            qfp = "Q4" if fp == "FY" else fp
            out[(fy, qfp)] = {**rec, "val": rec["val"] - prev, "end": rec["end"]}
            prev = rec["val"]
    return out


def _earliest_filed_map(facts: dict) -> dict[tuple[int, str], date]:
    """{(fy, fp): earliest `filed` date} across the core flow concepts — when the quarter FIRST
    became public. Deliberately the MIN, not `_pick`'s max: `_pick` prefers restated values (filed
    later as comparatives), but availability for point-in-time gating is the original 10-Q/10-K.
    Q4 additionally considers annual (FY) facts, since Q4 is typically derived from the 10-K."""
    out: dict[tuple[int, str], date] = {}

    def _note(key: tuple[int, str], filed_s: str | None) -> None:
        if not filed_s:
            return
        d = date.fromisoformat(filed_s)
        if key not in out or d < out[key]:
            out[key] = d

    for concept, unit in (("revenue", "USD"), ("operating_income", "USD"),
                          ("net_income", "USD"), ("eps", "USD/shares")):
        for r in _concept_facts(facts, concept, unit):
            dur = _dur_days(r)
            fy, fp = r.get("fy"), r.get("fp")
            if dur is None or fy is None:
                continue
            if 80 <= dur <= 100 and fp in _QTR_ORDER:
                _note((fy, fp), r.get("filed"))
            elif 350 <= dur <= 380 and fp == "FY":
                _note((fy, "Q4"), r.get("filed"))
    return out


def _instant_map(facts: dict, concept: str, unit: str = "USD") -> dict[str, float]:
    """{end_date: val} for point-in-time balance-sheet concepts (latest filed wins)."""
    recs = _concept_facts(facts, concept, unit)
    buckets: dict[str, list[dict]] = {}
    for r in recs:
        if r.get("start"):  # instant facts have no start
            continue
        buckets.setdefault(r["end"], []).append(r)
    return {k: _pick(v)["val"] for k, v in buckets.items()}


def _flow_quarterly(
    facts: dict, concept: str, unit: str = "USD", derive_q4: bool = True
) -> dict[tuple[int, str], dict]:
    """Quarterly map for an income-statement (flow) concept: discrete 90d facts +
    derived Q4 (= FY − Q1 − Q2 − Q3).

    derive_q4 must be False for per-share metrics (EPS): subtracting per-share figures
    across a fiscal year is invalid when a stock split occurred mid-year (it produced
    e.g. NVDA Q4 EPS = -4.49). Derived-Q4 EPS is left absent rather than wrong; it can be
    recomputed later from Q4 net income / diluted shares.
    """
    recs = _concept_facts(facts, concept, unit)
    q = _three_month_map(recs)
    if not derive_q4:
        return q
    annual = _annual_map(recs)
    for fy, arec in annual.items():
        if (fy, "Q4") in q:
            continue
        parts = [q.get((fy, fp)) for fp in ("Q1", "Q2", "Q3")]
        if all(parts):
            q[(fy, "Q4")] = {
                "val": arec["val"] - sum(p["val"] for p in parts),
                "end": arec["end"],
                "_derived": True,
            }
    return q


# ── assembly ─────────────────────────────────────────────────────────────────

def extract_quarters(ticker: str, limit: int | None = None) -> list[EdgarQuarter]:
    """Build the full quarterly financial history for a ticker from EDGAR."""
    cik = get_cik(ticker)
    if cik is None:
        raise ValueError(f"No CIK for ticker {ticker}")
    facts = fetch_companyfacts(cik)["facts"]

    rev = _flow_quarterly(facts, "revenue")
    cor = _flow_quarterly(facts, "cost_of_revenue")
    gp = _flow_quarterly(facts, "gross_profit")
    oi = _flow_quarterly(facts, "operating_income")
    ni = _flow_quarterly(facts, "net_income")
    eps = _flow_quarterly(facts, "eps", unit="USD/shares", derive_q4=False)
    ocf = _ytd_standalone(_concept_facts(facts, "operating_cash_flow", "USD"))
    capex = _ytd_standalone(_concept_facts(facts, "capex", "USD"))
    assets = _instant_map(facts, "total_assets")
    equity = _instant_map(facts, "total_equity")
    cash = _instant_map(facts, "cash_and_equivalents")
    # 4.1: debt components, share counts, capital-return flows
    debt_ltnc = _instant_map(facts, "debt_lt_noncurrent")
    debt_ltc = _instant_map(facts, "debt_lt_current")
    debt_lt_total = _instant_map(facts, "debt_lt_total")
    debt_st = _instant_map(facts, "debt_st_borrowings")
    shares_inst = _instant_map(facts, "shares_outstanding_instant", unit="shares")
    shares_wavg = _flow_quarterly(facts, "shares_diluted_wavg", unit="shares", derive_q4=False)
    sbc = _ytd_standalone(_concept_facts(facts, "stock_based_comp", "USD"))
    buybacks = _ytd_standalone(_concept_facts(facts, "buybacks", "USD"))

    keys = set(rev) | set(ni) | set(eps) | set(oi)
    filed_map = _earliest_filed_map(facts)
    quarters: list[EdgarQuarter] = []
    for (fy, fp) in keys:
        end_s = (rev.get((fy, fp)) or ni.get((fy, fp)) or eps.get((fy, fp)) or oi.get((fy, fp)))["end"]
        end = date.fromisoformat(end_s)
        eq = EdgarQuarter(fy=fy, fp=fp, period_end_date=end)
        filed = filed_map.get((fy, fp))
        # sanity: a filing can't precede the period it reports; bad metadata → leave None (75d fallback)
        eq.filed_date = filed if filed is not None and filed >= end else None

        def take(m, attr, name):
            r = m.get((fy, fp))
            if r is not None:
                setattr(eq, attr, r["val"])
                if r.get("_derived"):
                    eq.derived.append(name)

        take(rev, "revenue", "revenue")
        take(oi, "operating_income", "operating_income")
        take(ni, "net_income", "net_income")
        take(eps, "eps", "eps")
        take(ocf, "operating_cash_flow", "operating_cash_flow")

        # gross profit: filed GrossProfit, else revenue - cost_of_revenue
        gpr = gp.get((fy, fp))
        if gpr is not None:
            eq.gross_profit = gpr["val"]
        elif eq.revenue is not None and (c := cor.get((fy, fp))) is not None:
            eq.gross_profit = eq.revenue - c["val"]
            eq.derived.append("gross_profit")

        # FCF = OCF - capex
        cx = capex.get((fy, fp))
        if eq.operating_cash_flow is not None and cx is not None:
            eq.free_cash_flow = eq.operating_cash_flow - cx["val"]
            eq.derived.append("free_cash_flow")

        eq.total_assets = assets.get(end_s)
        eq.total_equity = equity.get(end_s)
        eq.cash_and_equivalents = cash.get(end_s)

        # total_debt (4.1): prefer the explicit noncurrent + current split; fall back to the
        # LongTermDebt total. Add short-term borrowings/CP when filed. Composed → marked derived.
        ltnc, ltc = debt_ltnc.get(end_s), debt_ltc.get(end_s)
        st = debt_st.get(end_s) or 0.0
        if ltnc is not None:
            eq.total_debt = ltnc + (ltc or 0.0) + st
            eq.derived.append("total_debt")
        elif (lt_tot := debt_lt_total.get(end_s)) is not None:
            eq.total_debt = lt_tot + st
            eq.derived.append("total_debt")

        # shares_outstanding (4.1): instant count at the balance-sheet date when filed; else the
        # quarter's weighted-average diluted count; else derived from NI/EPS (diluted, last resort).
        sh = shares_inst.get(end_s)
        if sh is None:
            wv = shares_wavg.get((fy, fp))
            sh = wv["val"] if wv else None
            if sh is not None:
                eq.derived.append("shares_outstanding")
        if sh is None and eq.net_income and eq.eps:
            sh = abs(eq.net_income / eq.eps)
            eq.derived.append("shares_outstanding")
        eq.shares_outstanding = sh

        take(sbc, "stock_based_comp", "stock_based_comp")
        take(buybacks, "buybacks", "buybacks")
        quarters.append(eq)

    # Collapse quarters that resolve to the same period_end_date — early/restated filings
    # (e.g. UBER pre-IPO 2019) can mislabel fy/fp, and the DB key is (ticker, period_end_date).
    # Keep the richest record (most populated core fields, prefer non-derived).
    def _richness(q: EdgarQuarter) -> tuple[int, int]:
        core = (q.revenue, q.operating_income, q.net_income, q.eps, q.free_cash_flow)
        return (sum(v is not None for v in core), -len(q.derived))

    dedup: dict[date, EdgarQuarter] = {}
    for q in quarters:
        cur = dedup.get(q.period_end_date)
        if cur is None or _richness(q) > _richness(cur):
            dedup[q.period_end_date] = q
    quarters = sorted(dedup.values(), key=lambda x: (x.fy, _QTR_ORDER[x.fp]), reverse=True)
    return quarters[:limit] if limit else quarters


# ── ingestion ─────────────────────────────────────────────────────────────────
# NOTE: EDGAR is the source of truth for the income-statement + cash-flow spine, and (4.1,
# 2026-06-11) the balance-sheet completion: total_debt (composed from LT nc/current + ST
# borrowings), shares_outstanding (instant → weighted-diluted → NI/EPS fallback), SBC and
# buybacks (YTD-differenced flows, like OCF).

# Fields scoring/forecasting depend on — all covered by the EDGAR extraction.
_EDGAR_FIELDS = (
    "revenue", "gross_profit", "operating_income", "net_income", "eps",
    "free_cash_flow", "operating_cash_flow", "total_assets", "total_equity",
    "cash_and_equivalents", "total_debt", "shares_outstanding",
    "stock_based_comp", "buybacks",
)


async def ingest_financials_edgar(db: AsyncSession, ticker: str) -> int:
    """Upsert the full EDGAR quarterly history into `financials` with provenance,
    then remove any stale non-EDGAR (yfinance) rows for the ticker so the ~2-day
    period-end offset doesn't leave duplicates. Returns rows upserted."""
    cik = get_cik(ticker)
    if cik is None:
        raise ValueError(f"No SEC CIK for ticker {ticker}")
    quarters = await asyncio.to_thread(extract_quarters, ticker)
    if not quarters:
        raise ValueError(f"EDGAR returned no quarters for {ticker}")

    url = FACTS_URL.format(cik=cik)
    today = date.today()
    rows = [
        {
            "ticker": ticker,
            "period": q.label,
            "period_end_date": q.period_end_date,
            "filed_date": q.filed_date,
            **{f: getattr(q, f) for f in _EDGAR_FIELDS},
            "source": "edgar",
            "source_url": url,
            "as_of": today,
        }
        for q in quarters
    ]

    stmt = insert(Financial).values(rows)
    update_cols = {c: getattr(stmt.excluded, c) for c in
                   ("period", "filed_date", *_EDGAR_FIELDS, "source", "source_url", "as_of")}
    stmt = stmt.on_conflict_do_update(constraint="uq_fin_ticker_period", set_=update_cols)
    await db.execute(stmt)

    # Drop stale rows from the previous source (date offset means they won't have conflicted).
    await db.execute(
        delete(Financial).where(
            Financial.ticker == ticker,
            Financial.source.is_distinct_from("edgar"),
        )
    )
    await db.commit()
    logger.info("[edgar] upserted %d quarterly financials for %s", len(rows), ticker)
    return len(rows)
