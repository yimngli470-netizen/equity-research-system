"""Pure checks for a cash-constrained alternative to requested stock repurchases."""
from copy import deepcopy
from datetime import date

import pytest

from app.forecast.model import _add_months
from app.valuation_model.economics import ValuationPolicy, window_total
from app.valuation_model.equity import equity_dcf
from app.valuation_model.funding import funded_share_path


AT = date(2026, 1, 1)
POLICY = ValuationPolicy(5, .025, .5, "test")


def quarters(shares=None, *, ni=100., revenue=1000.):
    counts = shares if shares is not None else [1000.] * 12
    return [{"q": i + 1, "end_approx": _add_months(AT, 3 * (i + 1)).isoformat(),
             "revenue": revenue, "operating_income": ni * 1.25, "net_income": ni,
             "operating_margin": ni * 1.25 / revenue, "shares": count,
             "eps": round(ni / count, 3), "rationale": "unchanged business assumptions"}
            for i, count in enumerate(counts)]


def fund(rows, shares=1000., *, conversion=1., price=10., sbc=.01):
    return funded_share_path(rows, shares, conversion=conversion,
                             reference_price=price, stock_comp_ratio=sbc)


def dcf(rows, shares=1000., *, conversion=1., price=10., sbc=.01):
    return equity_dcf(rows, conversion, .10, POLICY, AT, _add_months(AT, 12), shares,
                      reference_price=price, stock_comp_ratio=sbc)


def test_fundable_forecast_is_preserved_exactly_including_eps_precision():
    raw = quarters([1000. - 2 * (i + 1) for i in range(12)])
    before = deepcopy(raw)
    funded, changes = fund(raw)
    assert changes == [] and funded == raw == before
    assert funded is not raw and all(a is not b for a, b in zip(funded, raw))
    assert dcf(funded)["fair_value_per_share"] > 0


def test_binding_constraints_reduce_repurchases_and_carry_unretired_shares_forward():
    # $10 SBC + 20 requested retirements × $10 = $210 desired versus $100 FCF.
    raw = quarters([1000. - 20 * (i + 1) for i in range(12)])
    before = deepcopy(raw)
    funded, changes = fund(raw)
    assert len(changes) == 12
    assert funded[0]["shares"] == pytest.approx(991.)
    assert funded[-1]["shares"] == pytest.approx(892.)
    assert changes[0]["desired_repurchase"] == 210.
    assert changes[0]["funded_repurchase"] == pytest.approx(100.)
    assert changes[0]["additional_shares"] == pytest.approx(11.)
    assert changes[-1]["cumulative_additional_shares"] == pytest.approx(132.)
    assert raw == before  # stored assumptions and forecast paths were not rewritten
    for old, new in zip(raw, funded):
        for key in ("q", "end_approx", "revenue", "operating_income", "operating_margin", "net_income", "rationale"):
            assert new[key] == old[key]
        assert new["requested_shares"] == old["shares"]
        assert new["requested_eps"] == old["eps"]
        assert new["eps"] == pytest.approx(new["net_income"] / new["shares"])
    assert window_total(funded, AT, _add_months(AT, 12), "eps") < window_total(raw, AT, _add_months(AT, 12), "eps")
    assert window_total(funded, _add_months(AT, 12), _add_months(AT, 24), "eps") < window_total(raw, _add_months(AT, 12), _add_months(AT, 24), "eps")
    result = dcf(funded)  # the separate strict verifier accepts the derived path
    assert result["fair_value_per_share"] > 0 and result["price_at_horizon"] > 0
    assert all(s["repurchase_cash"] <= s["reported_fcf"] + 1e-6 for s in result["cash_flows"][:12])
    repeated, repeated_changes = fund(funded)
    assert repeated == funded and repeated_changes == []


def test_one_constraint_does_not_force_catch_up_buybacks_in_later_quarters():
    raw = quarters([980.] + [980. + i for i in range(1, 12)])
    funded, changes = fund(raw)
    assert len(changes) == 1
    assert funded[0]["shares"] == 991.
    assert all(q["shares"] == old["shares"] + 11. for q, old in zip(funded, raw))
    # Later requested issuance is retained; no automatic extra retirement spends future FCF.
    assert all(q["shares"] - p["shares"] == 1. for p, q in zip(funded, funded[1:]))
    assert all(s["repurchase_cash"] == 0. for s in dcf(funded)["cash_flows"][1:12])


def test_issuance_beyond_stock_compensation_is_preserved_without_cash_proceeds():
    raw = quarters([1000. + 5 * (i + 1) for i in range(12)])
    funded, changes = fund(raw)
    assert funded == raw and changes == []
    explicit = dcf(funded)["cash_flows"][:12]
    assert all(s["reported_fcf"] == s["value"] == 100. for s in explicit)
    assert all(s["repurchase_cash"] == 0. for s in explicit)


def test_per_share_values_include_the_unretired_shares_after_the_target_date():
    raw = quarters([1000. - 20 * (i + 1) for i in range(12)])
    funded, _ = fund(raw)
    result = dcf(funded)
    terminal = date.fromisoformat(result["cash_flows"][-1]["end"])
    # Keep the actual distributable cash schedule fixed, but incorrectly pretend the
    # requested share retirements happened. This isolates the dilution correction.
    for start, key in ((AT, "fair_value_per_share"), (_add_months(AT, 12), "price_at_horizon")):
        unfunded_claim = 0.
        for i, stream in enumerate(result["cash_flows"]):
            stop = date.fromisoformat(stream["end"])
            if stop > start:
                requested_count = raw[min(i, 11)]["shares"]
                unfunded_claim += stream["value"] / requested_count / 1.1 ** ((stop - start).days / 365.25)
        unfunded_claim += (result["terminal_value_per_share"] * result["terminal_shares"] / raw[-1]["shares"]
                          / 1.1 ** ((terminal - start).days / 365.25))
        assert result[key] < unfunded_claim


def test_large_share_counts_and_tiny_cash_budgets_pass_strict_verification():
    initial = 24_400_000_000.
    raw = quarters([initial * .9985 ** (i + 1) for i in range(12)], ni=.02, revenue=1.)
    funded, changes = fund(raw, initial, price=217.55, sbc=.015)
    assert changes
    result = dcf(funded, initial, price=217.55, sbc=.015)
    assert all(s["repurchase_cash"] <= s["reported_fcf"] + 1e-6 for s in result["cash_flows"][:12])


def test_negative_fcf_is_an_operating_funding_gap_not_an_assumed_financing_source():
    with pytest.raises(ValueError, match="Operating funding gap.*cash reserves and financing are not modeled"):
        fund(quarters(ni=-100.))


def test_funded_explicit_path_does_not_hide_an_unfunded_cash_settled_tail():
    # $250 SBC, $150 noncash issuance and $100 repurchases fit the explicit cash budget.
    # Freezing shares then requires cash compensation that the transition cannot fund.
    raw = quarters([1000. + 15 * (i + 1) for i in range(12)])
    funded, changes = fund(raw, sbc=.25)
    assert funded == raw and changes == []
    with pytest.raises(ValueError, match="Operating funding gap in cash-settled tail"):
        dcf(funded, sbc=.25)


@pytest.mark.parametrize("case", ["empty", "missing_income", "bad_shares", "bad_eps", "missing_date", "gap", "reverse"])
def test_incomplete_or_invalid_paths_fail_closed(case):
    raw = quarters()
    if case == "empty":
        raw = []
    elif case == "missing_income":
        raw[0]["net_income"] = None
    elif case == "bad_shares":
        raw[0]["shares"] = 0.
    elif case == "bad_eps":
        raw[0]["eps"] = float("nan")
    elif case == "missing_date":
        raw[0].pop("end_approx")
    elif case == "gap":
        raw.pop(1)
    elif case == "reverse":
        raw = list(reversed(raw))
    with pytest.raises(ValueError):
        fund(raw)


@pytest.mark.parametrize("parameter,bad", [("conversion", 0), ("reference_price", 0),
                                          ("stock_comp_ratio", -.1), ("stock_comp_ratio", float("nan"))])
def test_invalid_parameters_fail_closed(parameter, bad):
    kwargs = {"conversion": 1., "reference_price": 10., "stock_comp_ratio": .01}
    kwargs[parameter] = bad
    with pytest.raises(ValueError):
        funded_share_path(quarters(), 1000., **kwargs)
