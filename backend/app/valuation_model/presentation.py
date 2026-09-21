"""One response contract for current and historical valuation artifacts."""
from copy import deepcopy
from datetime import date
from app.valuation_model.economics import MODEL_VERSION
from app.valuation_model.target import scenario_summary


def _date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value) if value else None
    except (ValueError, TypeError):
        return None


def _current_method(method, *, as_of, forecast_as_of=None, today=None, latest_financial_end=None):
    """Apply the same current-use guard to targets, agent reports and compiled notes."""
    today = today or date.today()
    method = deepcopy(method or {})
    issues = list(method.get("issues") or [])
    if method.get("version") != MODEL_VERSION:
        method["status"] = "refresh_required"
        issues.append("Previous valuation model: refresh analysis to replace the old target and rebuild earnings paths.")
    artifact_date = _date(as_of)
    if artifact_date is None or artifact_date > today:
        method["status"] = "refresh_required"
        issues.append("Valuation has no valid calculation date; refresh before using it as a current target.")
    elif (today - artifact_date).days > 30:
        method["status"] = "refresh_required"
        issues.append("Valuation is more than 30 days old; refresh before using it as a current target.")
    modeled_end = _date(method.get("financial_end")) or _date(forecast_as_of)
    if latest_financial_end and modeled_end and latest_financial_end > modeled_end:
        method["status"] = "refresh_required"
        issues.append("A newer financial quarter is available than the underlying forecast.")
    method["issues"] = list(dict.fromkeys(issues))
    return method


def price_target_payload(pt, *, today=None, latest_financial_end=None):
    method = _current_method(pt.method, as_of=pt.as_of, forecast_as_of=pt.forecast_as_of,
                             today=today, latest_financial_end=latest_financial_end)
    ready = method.get("status") == "ready"
    return {
        "as_of": pt.as_of.isoformat(), "forecast_as_of": pt.forecast_as_of.isoformat() if pt.forecast_as_of else None,
        "price_at": pt.price_at, "fair_value": pt.fair_value if ready else None,
        "price_target": pt.price_target if ready else None, "horizon_months": pt.horizon_months,
        "upside": pt.upside if ready else None, "probabilities": pt.probabilities,
        "scenarios": scenario_summary(pt.scenarios) if ready else {}, "modes": pt.modes if ready else {},
        "method": method, "wacc": pt.wacc, "sensitivity": pt.sensitivity if ready else {},
        "street_target_mean": pt.street_target_mean,
    }


def valuation_report_payload(report, *, price_target=None, report_date=None, today=None, latest_financial_end=None):
    """Display current calculator values with separately dated prose, preserving stored history.

    Cached prose is not an independent numerical valuation. Reading an agent report uses the
    latest decision model's base scenario even when no new LLM call has occurred.
    """
    out = deepcopy(report)
    old_model = out.get("valuation_model") if isinstance(out.get("valuation_model"), dict) else {}
    current = price_target_payload(price_target, today=today, latest_financial_end=latest_financial_end) if price_target else {}
    method = current.get("method") or {"version": MODEL_VERSION, "status": "unavailable",
                                       "issues": ["No current deterministic valuation is available; run analysis to build dated scenarios."]}
    ready = method.get("status") == "ready"
    scenarios = current.get("scenarios") or {}
    base = scenarios.get("base") or {}
    fair, target = base.get("dcf_today"), base.get("blended")
    narrative_stale = not ready or any((
        old_model.get("version") != method.get("version"),
        old_model.get("as_of") != current.get("as_of"),
        old_model.get("forecast_as_of") != current.get("forecast_as_of"),
        (report.get("dcf_analysis") or {}).get("intrinsic_value_base") != fair,
        (report.get("target_price_range") or {}).get("mid") != target,
        report.get("current_price") != current.get("price_at"),
    ))
    narrative_date = old_model.get("as_of") or (_date(report_date).isoformat() if _date(report_date) else None)
    out["valuation_model"] = {
        "version": method.get("version"), "status": "verified" if ready else method.get("status", "unavailable"),
        "as_of": current.get("as_of"), "forecast_as_of": current.get("forecast_as_of"),
        "target_date": method.get("target_date"), "method": method, "issues": method["issues"],
        "narrative_as_of": narrative_date, "narrative_stale": narrative_stale,
        "source": "base scenario from the same stored deterministic calculator as the decision price target",
    }
    price = current.get("price_at")
    upside = fair / price - 1 if fair is not None and price and ready else None
    out["current_price"] = price
    out["dcf_analysis"] = {
        **{f"intrinsic_value_{name}": (scenarios.get(name) or {}).get("dcf_today") for name in ("bear", "base", "bull")},
        "assumptions": {"cost_of_equity": (current.get("wacc") or {}).get("cost_of_equity"),
                        "terminal_growth": method.get("terminal_growth")},
        "methodology_note": "Present equity DCF from the stored deterministic calculator. Future targets have a separate date.",
    }
    targets = [s["blended"] for s in scenarios.values() if s.get("blended") is not None]
    out["target_price_range"] = {"low": min(targets) if targets else None, "mid": target, "high": max(targets) if targets else None}
    out["margin_of_safety"] = upside
    verdict = "unknown" if upside is None else (
        "significantly_undervalued" if upside >= .30 else "moderately_undervalued" if upside >= .10 else
        "significantly_overvalued" if upside <= -.30 else "moderately_overvalued" if upside <= -.10 else "fairly_valued")
    out["valuation_verdict"] = verdict
    out["valuation_score"] = {"significantly_undervalued": 1., "moderately_undervalued": .75,
        "fairly_valued": .5, "moderately_overvalued": .25, "significantly_overvalued": 0.}.get(verdict)
    tri = out.get("triangulation") if isinstance(out.get("triangulation"), dict) and not narrative_stale else {}
    street = current.get("street_target_mean")
    tri.update(your_fair_value=fair, your_target_price=target, street_mean_target=street,
               divergence_pct=round(target / street - 1, 4) if target is not None and street else None,
               comparison_basis="base future target vs street target; present DCF shown separately")
    out["triangulation"] = tri
    if narrative_stale:
        # The original prose can contain old dollar claims; retain it only in stored history.
        for key in ("regime", "multiples_analysis", "model_assessment", "consensus_comparison", "guidance_assessment", "signal"):
            out.pop(key, None)
        out["summary"] = (
            "Values reflect the current deterministic model. The earlier narrative needs a refresh to explain these assumptions."
            if ready else " ".join(method["issues"]) + " Refresh analysis before using valuation claims."
        )
    return out
