"""Regressions for filed earnings/cash flows and per-share valuation denominators."""

from datetime import date

import pytest

from app.ingestion import edgar


def record(value, start="2026-04-01", end="2026-06-30", fp="Q2", accn="filing-1", fy=2026):
    return {"start": start, "end": end, "val": value, "fp": fp, "fy": fy,
            "accn": accn, "filed": "2026-07-29", "form": "10-Q"}


def facts(**tags):
    return {"us-gaap": {tag: {"units": {unit: rows}} for tag, (unit, rows) in tags.items()}}


def extract(monkeypatch, data):
    monkeypatch.setattr(edgar, "get_cik", lambda ticker: 1)
    monkeypatch.setattr(edgar, "fetch_companyfacts", lambda cik: {"facts": data})
    return edgar.extract_quarters("TEST")


def test_profitloss_requires_matching_eps_denominator_and_preserves_parent():
    data = facts(
        ProfitLoss=("USD", [record(13_088e6)]),
        EarningsPerShareDiluted=("USD/shares", [record(2.68)]),
        WeightedAverageNumberOfDilutedSharesOutstanding=("shares", [record(4_887e6)]),
    )
    rows = edgar._reconciled_net_income_records(data)
    assert rows[0]["val"] == 13_088e6
    assert "EPS" in rows[0]["_basis"]
    # The same consolidated profit need not all belong to the parent.
    data["us-gaap"]["NetIncomeLoss"] = {"units": {"USD": [record(12_000e6)]}}
    assert [r["val"] for r in edgar._reconciled_net_income_records(data)] == [12_000e6]


@pytest.mark.parametrize("eps,shares,eps_start,shares_accn", [
    (2.50, 4_887e6, "2026-04-01", "filing-1"),  # minority/preferred gap
    (2.68, 4_887e6, "2026-01-01", "filing-1"),  # annual/quarter mismatch
    (2.68, 4_887e6, "2026-04-01", "different-filing"),  # split/restatement mixing
    (2.68, 0, "2026-04-01", "filing-1"),
])
def test_profitloss_is_not_unconditionally_parent_income(eps, shares, eps_start, shares_accn):
    data = facts(
        ProfitLoss=("USD", [record(13_088e6)]),
        EarningsPerShareDiluted=("USD/shares", [record(eps, start=eps_start)]),
        WeightedAverageNumberOfDilutedSharesOutstanding=("shares", [record(shares, accn=shares_accn)]),
    )
    assert edgar._reconciled_net_income_records(data) == []


def test_explicit_same_context_minority_deduction_is_valid_without_eps():
    data = facts(ProfitLoss=("USD", [record(609e6)]),
                 NetIncomeLossAttributableToNoncontrollingInterest=("USD", [record(50e6)]))
    assert edgar._reconciled_net_income_records(data)[0]["val"] == 559e6
    data["us-gaap"].pop("NetIncomeLossAttributableToNoncontrollingInterest")
    assert edgar._reconciled_net_income_records(data) == []


def test_q4_earnings_from_reconciled_annual_total_not_eps_subtraction(monkeypatch):
    spans = [("2025-01-01", "2025-03-31", "Q1", 110, 11),
             ("2025-04-01", "2025-06-30", "Q2", 240, 12),
             ("2025-07-01", "2025-09-30", "Q3", 390, 13),
             ("2025-01-01", "2025-12-31", "FY", 1300, 13)]
    profits, eps, shares = [], [], []
    for start, end, fp, income, count in spans:
        kw = dict(start=start, end=end, fp=fp, fy=2025)
        profits.append(record(income, **kw))
        eps.append(record(round(income / count, 2), **kw))
        shares.append(record(count, **kw))
    data = facts(ProfitLoss=("USD", profits), EarningsPerShareDiluted=("USD/shares", eps),
                 WeightedAverageNumberOfDilutedSharesOutstanding=("shares", shares))
    quarters = extract(monkeypatch, data)
    q4 = next(q for q in quarters if q.fp == "Q4")
    assert q4.net_income == 560
    assert q4.eps is None
    # Annual diluted means cannot recover Q4: period-specific dilution tests differ.
    assert q4.shares_outstanding is None


def test_corning_cash_capex_tag_and_diluted_not_treasury_issued_shares(monkeypatch):
    q1 = dict(start="2026-01-01", end="2026-03-31", fp="Q1")
    ytd = dict(start="2026-01-01", end="2026-06-30", fp="Q2")
    data = facts(
        NetIncomeLoss=("USD", [record(371e6, **q1), record(559e6)]),
        NetCashProvidedByUsedInOperatingActivities=("USD", [record(362e6, **q1), record(2079e6, **ytd)]),
        PaymentsForCapitalImprovements=("USD", [record(332e6, **q1), record(754e6, **ytd)]),
        WeightedAverageNumberOfDilutedSharesOutstanding=("shares", [record(871e6, **q1), record(875e6)]),
        CommonStockSharesOutstanding=("shares", [{"end": "2026-06-30", "val": 861e6, "filed": "2026-07-29"}]),
        CommonStockSharesIssued=("shares", [{"end": "2026-06-30", "val": 1900e6, "filed": "2026-07-29"}]),
    )
    q2 = next(q for q in extract(monkeypatch, data) if q.period_end_date == date(2026, 6, 30))
    assert q2.free_cash_flow == 1295e6
    assert q2.shares_outstanding == 875e6
    # An issuance at period end is a real current claim even if the quarter mean is lower.
    data["us-gaap"]["CommonStockSharesOutstanding"]["units"]["shares"][0]["val"] = 900e6
    q2 = next(q for q in extract(monkeypatch, data) if q.fp == "Q2")
    assert q2.shares_outstanding == 900e6
    data["us-gaap"]["CommonStockSharesOutstanding"]["units"]["shares"][0]["val"] = 861e6
    data["us-gaap"].pop("WeightedAverageNumberOfDilutedSharesOutstanding")
    q2 = next(q for q in extract(monkeypatch, data) if q.fp == "Q2")
    assert q2.shares_outstanding == 861e6
    data["us-gaap"].pop("CommonStockSharesOutstanding")
    q2 = next(q for q in extract(monkeypatch, data) if q.fp == "Q2")
    assert q2.shares_outstanding is None
