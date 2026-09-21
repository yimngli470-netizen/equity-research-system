"""Pure valuation checks for dilution and funded shareholder distributions."""
from datetime import date

import pytest

from app.forecast.model import _add_months
from app.valuation_model.economics import ValuationPolicy
from app.valuation_model.equity import equity_dcf


AT = date(2026, 1, 1)
POLICY = ValuationPolicy(5, .025, .5, "test")


def projection(shares=None):
    counts = shares if shares is not None else [100.] * 12
    return [{"end_approx": _add_months(AT, 3 * (i + 1)).isoformat(),
             "revenue": 1000., "net_income": 100., "operating_income": 125.,
             "shares": count} for i, count in enumerate(counts)]


def value(rows=None, *, stock_comp_ratio=0., reference_price=10., target_months=12,
          normalized_income=None):
    return equity_dcf(rows if rows is not None else projection(), 1., .10, POLICY,
                      AT, _add_months(AT, target_months), 100.,
                      reference_price=reference_price, stock_comp_ratio=stock_comp_ratio,
                      normalized_income=normalized_income)


def test_dilution_after_target_reduces_both_present_and_future_value():
    constant = value()
    # The first year is identical: a target-date-only share adjustment cannot catch this.
    issued = value(projection([100.] * 4 + [100. * 1.01 ** i for i in range(1, 9)]))
    assert issued["target_shares"] == constant["target_shares"] == 100.
    assert issued["fair_value_per_share"] < constant["fair_value_per_share"]
    assert issued["price_at_horizon"] < constant["price_at_horizon"]
    assert issued["terminal_shares"] == pytest.approx(100. * 1.01 ** 8)
    # Noncash issuance supplies no extra cash that could conceal dilution.
    assert all(q["value"] == 100. for q in issued["cash_flows"][:12])
    assert issued["cash_flows"][4]["per_share"] == pytest.approx(100. / 101.)


def test_zero_net_dilution_requires_cash_to_offset_stock_compensation():
    uncompensated = value()
    result = value(stock_comp_ratio=.01)
    quarter = result["cash_flows"][0]
    assert quarter["stock_comp"] == 10.
    assert quarter["repurchase_cash"] == 10.
    assert quarter["value"] == 90.
    assert quarter["per_share"] == .9
    assert result["fair_value_per_share"] < uncompensated["fair_value_per_share"]


def test_gross_repurchase_funding_accounts_for_sbc_and_reference_price():
    counts = [100. - (i + 1) for i in range(12)]
    low = value(projection(counts), stock_comp_ratio=.01, reference_price=10.)
    high = value(projection(counts), stock_comp_ratio=.01, reference_price=20.)
    # $10 offsets SBC, and another $10/$20 retires one additional share.
    assert low["cash_flows"][0]["repurchase_cash"] == 20.
    assert high["cash_flows"][0]["repurchase_cash"] == 30.
    assert low["cash_flows"][0]["value"] == 80.
    assert high["fair_value_per_share"] < low["fair_value_per_share"]
    with pytest.raises(ValueError, match="cannot be funded"):
        value(projection([90.] * 12), stock_comp_ratio=.01)


def test_increasing_shares_never_create_cash_issuance_proceeds():
    result = value(projection([110. + i for i in range(12)]), stock_comp_ratio=.01)
    first = result["cash_flows"][0]
    # Net issuance exceeds the SBC share proxy. Excess issuance dilutes without cash proceeds.
    assert first["repurchase_cash"] == 0.
    assert first["reported_fcf"] == first["value"] == 100.
    assert first["per_share"] == pytest.approx(100. / 110.)


def test_cash_settled_tail_removes_sbc_addback_but_does_not_charge_it_twice():
    result = value(stock_comp_ratio=.01)
    # Latest annual GAAP income is $400; $40 SBC must become a cash expense with shares frozen.
    assert result["cash_settlement_conversion"] == pytest.approx(.90)
    assert result["terminal_conversion"] == pytest.approx(1 - .025 / .15)
    tail = result["cash_flows"][12:]
    assert all(s["shares"] == 100. and s["phase"] == "cash_settled_tail" for s in tail)
    assert tail[0]["cash_conversion"] == pytest.approx((.90 + (1 - .025 / .15)) / 2)
    assert tail[-1]["value"] == pytest.approx(result["ni_years"][-1] * (1 - .025 / .15))
    assert result["terminal_value_per_share"] == pytest.approx(tail[-1]["value"] / 100. * 1.025 / .075)


def test_per_share_cash_flow_audit_reconstructs_values_and_paid_cash_is_excluded():
    result = value(projection([100. * 1.01 ** (i + 1) for i in range(12)]), stock_comp_ratio=.01)
    terminal_end = date.fromisoformat(result["cash_flows"][-1]["end"])
    def independent_pv(at):
        amounts = []
        for cash in result["cash_flows"]:
            start, stop = date.fromisoformat(cash["start"]), date.fromisoformat(cash["end"])
            if stop > at:
                fraction = (stop - max(start, at)).days / (stop - start).days
                amounts.append(cash["value"] / cash["shares"] * fraction / 1.1 ** ((stop-at).days / 365.25))
        return sum(amounts) + result["terminal_value_per_share"] / 1.1 ** ((terminal_end-at).days / 365.25)
    assert result["fair_value_per_share"] == pytest.approx(independent_pv(AT), abs=.01)
    assert result["price_at_horizon"] == pytest.approx(independent_pv(_add_months(AT, 12)), abs=.01)
    assert result["price_at_horizon"] < result["fair_value_per_share"] * 1.1
    # An intra-quarter target prorates that quarter's remaining distribution.
    partial = value(projection([100. * 1.01 ** (i + 1) for i in range(12)]),
                    stock_comp_ratio=.01, target_months=13)
    assert partial["price_at_horizon"] == pytest.approx(independent_pv(_add_months(AT, 13)), abs=.01)


def test_cyclical_tail_still_converges_to_normalized_income():
    result = value(normalized_income=200.)
    assert result["ni_years"][-1] == pytest.approx(200. * 1.025 ** 5)


@pytest.mark.parametrize("keyword, invalid", [("reference_price", 0), ("reference_price", float("nan")),
                                               ("stock_comp_ratio", -.01), ("stock_comp_ratio", float("inf"))])
def test_invalid_funding_inputs_fail_closed(keyword, invalid):
    with pytest.raises(ValueError):
        value(**{keyword: invalid})
