"""Dated equity cash-flow proxy: reported FCF assumes zero net borrowing.

Discount at cost of equity, with no second subtraction of debt. Historical FCF includes
financing costs; the operating normalization uses a historical after-financing conversion too.
This is an explicitly labeled approximation, not company-reconciled non-GAAP or an FCFF DCF.
Cash available after funded repurchases is distributed per projected share. Issuance is
noncash dilution; no financing proceeds are invented. Terminal retained earnings fund growth.
"""
from __future__ import annotations

from datetime import date

from app.forecast.model import _add_months
from app.valuation_model.economics import ValuationPolicy, number


def equity_dcf(quarters: list[dict], conversion: float, rate: float, policy: ValuationPolicy,
               as_of: date, target_date: date, shares_now: float, *, reference_price: float,
               stock_comp_ratio: float, operating=False,
               tax_rate=.21, terminal_roe=.15, normalized_income=None) -> dict:
    """Value one continuing share, including dilution after the target date.

    ``shares_now`` anchors the forecast's first quarter at its preceding actual date.
    Repurchases use a declared constant reference price, not an assumed future model price.
    """
    if any(number(v) is None for v in (conversion, rate, shares_now, terminal_roe,
                                      reference_price, stock_comp_ratio, tax_rate,
                                      policy.terminal_growth)):
        raise ValueError("DCF inputs must be finite")
    if rate <= policy.terminal_growth or shares_now <= 0 or conversion <= 0:
        raise ValueError("Discount rate must exceed terminal growth and shares must be positive")
    if reference_price <= 0 or stock_comp_ratio < 0 or not 0 <= tax_rate <= 1:
        raise ValueError("A positive repurchase reference price and nonnegative SBC ratio are required")
    if normalized_income is not None and (number(normalized_income) is None or normalized_income <= 0):
        raise ValueError("Normalized income must be finite and positive")
    qs = sorted(quarters, key=lambda q: q["end_approx"])
    if len(qs) < 8:
        raise ValueError("DCF needs at least eight explicit quarters")
    prev = _add_months(date.fromisoformat(qs[0]["end_approx"]), -3)
    if not prev <= as_of < target_date:
        raise ValueError("DCF dates must be covered by the forecast")
    streams, incomes, stock_comp = [], [], []
    target_shares = current_shares = previous_shares = shares_now
    for q in qs:
        end = date.fromisoformat(q["end_approx"])
        income = number(q.get("operating_income" if operating else "net_income"))
        revenue, shares = number(q.get("revenue")), number(q.get("shares"))
        if income is None or revenue is None or revenue < 0 or not 75 <= (end - prev).days <= 100:
            raise ValueError("Incomplete cash-flow projection")
        if shares is None or shares <= 0:
            raise ValueError("Missing positive projected share count")
        if operating:
            income *= 1 - tax_rate
        reported_fcf = income * conversion
        sbc = revenue * stock_comp_ratio
        share_change = shares - previous_shares
        repurchases = max(0., sbc - share_change * reference_price)
        # SBC is already added back in reported FCF. To reach the forecast's NET share
        # path, buybacks must offset any issuance beyond that path, plus net retirements.
        if end > as_of and repurchases > max(0., reported_fcf) + max(1e-6, abs(reported_fcf) * 1e-9):
            raise ValueError(f"Repurchases through {end} cannot be funded by projected quarterly FCF alone; cash reserves and borrowing are not modeled")
        cash = reported_fcf - repurchases
        streams.append({"start": prev, "end": end, "value": cash, "shares": shares,
                        "per_share": cash / shares, "reported_fcf": reported_fcf,
                        "stock_comp": sbc, "repurchase_cash": repurchases,
                        "net_share_change": share_change, "phase": "explicit"})
        incomes.append(income)
        stock_comp.append(sbc)
        if prev <= as_of <= end:
            current_shares = previous_shares + (as_of - prev).days / (end - prev).days * share_change
        if prev < target_date <= end:
            fraction = (target_date - prev).days / (end - prev).days
            target_shares = previous_shares + fraction * share_change
        prev, previous_shares = end, shares
    if target_date > prev:
        raise ValueError("Forecast does not cover target-date share count")

    latest_income, prior_income = sum(incomes[-4:]), sum(incomes[-8:-4])
    if latest_income <= 0 or prior_income <= 0:
        raise ValueError("No sustainable positive earnings base for terminal value")
    raw_growth = latest_income / prior_income - 1
    # Guard extreme earnings rebound extrapolation; preserve the adjustment in provenance.
    growth = max(-.5, min(.5, raw_growth))
    tail_years = max(1, policy.maturity_year - len(qs) // 4)
    terminal_roe = max(policy.terminal_growth + .01, terminal_roe)
    terminal_conversion = max(0, min(1, 1 - policy.terminal_growth / terminal_roe))
    # Beyond the explicit share path, compensation is cash settled and shares freeze.
    # Remove the SBC add-back from the starting cash bridge before fading toward a
    # terminal payout derived from GAAP income. Do not subtract SBC again at terminal.
    cash_settlement_conversion = conversion - sum(stock_comp[-4:]) / latest_income
    annual_incomes = []
    cycle_start = latest_income
    cycle_terminal = normalized_income * (1 + policy.terminal_growth) ** policy.maturity_year if normalized_income else None
    for i in range(1, tail_years + 1):
        fraction = i / tail_years
        g = growth + (policy.terminal_growth - growth) * fraction
        latest_income *= 1 + g
        if cycle_terminal is not None:
            latest_income = cycle_start + (cycle_terminal - cycle_start) * fraction
        c = cash_settlement_conversion + (terminal_conversion - cash_settlement_conversion) * fraction
        end = _add_months(prev, 12)
        cash = latest_income * c
        if cash < 0:
            raise ValueError(f"Operating funding gap in cash-settled tail through {end}: cash flow is negative; cash reserves and financing are not modeled")
        streams.append({"start": prev, "end": end, "value": cash, "shares": previous_shares,
                        "per_share": cash / previous_shares, "cash_conversion": c,
                        "phase": "cash_settled_tail"})
        annual_incomes.append(latest_income)
        prev = end
    terminal_value_per_share = streams[-1]["per_share"] * (1 + policy.terminal_growth) / (rate - policy.terminal_growth)

    def pv(at):
        total = 0.0
        for stream in streams:
            start, stop, cash = stream["start"], stream["end"], stream["per_share"]
            if stop <= at:
                continue
            remaining = (stop - max(start, at)).days / (stop - start).days
            total += cash * remaining / (1 + rate) ** ((stop - at).days / 365.25)
        return total + terminal_value_per_share / (1 + rate) ** ((prev - at).days / 365.25)

    now, future = pv(as_of), pv(target_date)
    if now <= 0 or future <= 0:
        raise ValueError("Equity cash-flow model does not support positive equity value")
    return {
        "fair_value_per_share": round(now, 2),
        "price_at_horizon": round(future, 2),
        "equity_value": round(now * current_shares), "enterprise_value": None,
        "discount_rate": rate, "cash_flow_basis": "per-share equity distributions after funded repurchases, zero net borrowing",
        "fcf_conversion": conversion, "terminal_growth": policy.terminal_growth,
        "terminal_roe": terminal_roe, "terminal_conversion": terminal_conversion,
        "maturity_year": policy.maturity_year, "target_shares": target_shares,
        "valuation_shares": current_shares, "terminal_shares": previous_shares,
        "repurchase_reference_price": reference_price, "stock_comp_ratio": stock_comp_ratio,
        "cash_settlement_conversion": cash_settlement_conversion,
        "terminal_value_per_share": terminal_value_per_share,
        "fcf_years": [round(sum(s["value"] for s in streams[i:i + 4])) for i in range(0, len(qs), 4)]
                     + [round(s["value"]) for s in streams[len(qs):]],
        "ni_years": [round(sum(incomes[i:i + 4])) for i in range(0, len(incomes), 4)] + annual_incomes,
        "cash_flows": [{**s, "start": s["start"].isoformat(), "end": s["end"].isoformat()} for s in streams],
        "notes": ["Reported FCF assumes zero net borrowing; cash remaining after funded repurchases is distributed per projected share. "
                  "no separate cash/investment asset value is added. Refinancing and asset sales are not modeled.",
                  "Terminal retention = terminal growth / declared sustainable ROE (15% policy prior).",
                  "Operating mode normalizes the earnings-to-cash bridge; it is not adjusted EPS."]
                 + (["Cyclical tail reverts to normalized earning power, rather than extrapolating peak margins."] if normalized_income else [])
                 + ["SBC = forecast revenue × historical SBC/revenue. Repurchase cash = max(0, SBC − net share issuance × constant reference price). "
                    "Share issuance supplies no assumed financing proceeds; repurchases must be funded by forecast FCF.",
                    "Each distribution uses its projected share count, including dilution after the target date. "
                    "After the explicit forecast, diluted shares freeze and compensation is cash settled; the cash bridge fades to terminal retention without a second SBC charge."]
                 + ([f"Tail earnings growth {raw_growth:.1%} limited to {growth:.1%}"] if growth != raw_growth else []),
    }
