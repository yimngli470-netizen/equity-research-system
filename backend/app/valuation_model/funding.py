"""Cash-constrained alternative to a requested forecast share path.

Operating assumptions remain unchanged. When quarterly FCF cannot fund the requested
gross repurchases, fewer shares are retired; the difference remains in all later quarters.
No existing cash balance, borrowing, or cash proceeds from issuance are assumed.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
import math

from app.valuation_model.economics import number


def funded_share_path(quarters: list[dict], shares_now: float, *, conversion: float,
                      reference_price: float, stock_comp_ratio: float) -> tuple[list[dict], list[dict]]:
    """Return a new funded path and an audit entry for each binding cash constraint.

    Requested net issuance is preserved, including issuance beyond the SBC share proxy.
    Net repurchases are reduced only as needed to fit that quarter's modeled cash budget.
    Unchanged paths retain their original EPS precision and all supplied fields exactly.
    """
    parameters = (shares_now, conversion, reference_price, stock_comp_ratio)
    if any(number(v) is None for v in parameters):
        raise ValueError("Share funding inputs must be finite numbers")
    if shares_now <= 0 or conversion <= 0 or reference_price <= 0 or stock_comp_ratio < 0:
        raise ValueError("Share funding requires positive shares, conversion and reference price, and nonnegative SBC")
    if not isinstance(quarters, list) or not quarters:
        raise ValueError("A nonempty quarterly forecast is required for share funding")

    output, adjustments = [], []
    previous_requested = previous_funded = float(shares_now)
    previous_date = None
    carry = Decimal(0)
    for row in quarters:
        if not isinstance(row, dict):
            raise ValueError("Each share-funding quarter must be an object")
        try:
            end = date.fromisoformat(row["end_approx"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Share funding requires an ISO quarter-end date") from None
        if previous_date is not None and not 75 <= (end - previous_date).days <= 100:
            raise ValueError("Share funding requires consecutive chronological quarters")
        ni, revenue, requested = (number(row.get(k)) for k in ("net_income", "revenue", "shares"))
        if ni is None or revenue is None or requested is None or revenue < 0 or requested <= 0:
            raise ValueError("Share funding requires finite earnings/revenue and positive requested shares")
        if "eps" in row and number(row["eps"]) is None:
            raise ValueError("Requested forecast EPS must be finite")
        fcf, sbc = ni * conversion, revenue * stock_comp_ratio
        if not math.isfinite(fcf) or not math.isfinite(sbc):
            raise ValueError("Projected cash funding amounts must be finite")
        if fcf < 0:
            raise ValueError(f"Operating funding gap through {end}: projected FCF is negative; cash reserves and financing are not modeled")

        requested_change = requested - previous_requested
        desired = max(0., sbc - requested_change * reference_price)
        if not math.isfinite(desired):
            raise ValueError("Projected repurchase funding must be finite")
        # Same tolerance as the strict DCF verifier: do not rewrite an otherwise funded
        # forecast merely because binary arithmetic puts a cash total a few ulps over budget.
        tolerance = max(1e-6, abs(fcf) * 1e-9)
        binds = desired > fcf + tolerance
        funded_budget = min(desired, fcf)
        shortfall = desired - funded_budget if binds else 0.
        with localcontext() as context:
            context.prec = 50
            if binds:
                carry += Decimal.from_float(shortfall) / Decimal.from_float(float(reference_price))
            funded = float(Decimal.from_float(requested) + carry) if carry else requested
        if not math.isfinite(funded) or funded <= 0:
            raise ValueError("Funded share count must remain finite and positive")

        funded_cash = max(0., sbc - (funded - previous_funded) * reference_price)
        # Converting a fractional share back to binary float may round down. Move only
        # toward fewer repurchases, never beyond the requested cash amount or FCF budget.
        while funded_cash > funded_budget + tolerance:
            funded = math.nextafter(funded, math.inf)
            if not math.isfinite(funded):
                raise ValueError("Funded share count cannot be represented safely")
            funded_cash = max(0., sbc - (funded - previous_funded) * reference_price)
        carry = Decimal.from_float(funded) - Decimal.from_float(requested)

        updated = dict(row)
        if funded != requested:
            updated.update(requested_shares=row.get("requested_shares", row["shares"]),
                           requested_eps=row.get("requested_eps", row.get("eps")),
                           shares=funded, eps=ni / funded,
                           funding_carry_shares=float(carry))
        if binds:
            adjustments.append({
                "end_approx": end.isoformat(), "requested_shares": requested,
                "funded_shares": funded, "desired_repurchase": desired,
                "funded_repurchase": funded_cash, "fcf": fcf, "stock_comp": sbc,
                "requested_share_change": requested_change,
                "additional_shares": (funded - previous_funded) - requested_change,
                "cumulative_additional_shares": float(carry),
                "reference_price": reference_price,
                "reason": "Quarterly FCF limits gross repurchases; unretired shares carry forward. "
                          "Operating assumptions are unchanged; no cash reserves, borrowing or issuance proceeds are assumed.",
            })
        output.append(updated)
        previous_requested, previous_funded, previous_date = requested, funded, end
    return output, adjustments
