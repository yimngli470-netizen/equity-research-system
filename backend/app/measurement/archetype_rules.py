"""Rule-based provisional archetype classifier (roadmap 6.1b) — the ~zero-LLM tier-1 label.

The watchlist path classifies archetype with a grounded LLM (`ingestion/archetype.py`): at ~13 names
the LLM's world knowledge is worth one Sonnet call. But tier-1 batches ~520 SPX+NDX names, where a
per-name LLM call is the exact cost we're avoiding. So here we encode the SAME discriminators the LLM
prompt cites — revenue-growth volatility, peak-to-trough drawdown, margin level/stability, loss
frequency, capex intensity — into a deterministic decision tree over the measured `QuantProfile`.

Thresholds were calibrated against the 13 grounded-LLM watchlist labels (10/11 agreement; the one
miss, a GAAP-negative growth semi, is the kind of world-knowledge call only the LLM gets right). Two
discriminators carried most of the signal: (1) *durable* >25% average growth over ~8yr overrides
cyclicality and loss-history — that's the "is NVDA cyclical or secular" / "is UBER a turnaround"
call; (2) platforms are separated from ordinary high-margin compounders by *ultra-stable* margins
(GOOGL/META margins barely move; AVGO's swing with its acquisitions).

The label is marked `archetype_source="rules"` and is explicitly *provisional*: promoting a name to
the watchlist (6.1e) re-runs the grounded-LLM classifier and upgrades it to `"llm"`. ML M2
(unsupervised clustering over the ~520 profiles) will later validate whether these 6 buckets — and
these thresholds — are the right ones; until then this is a transparent, tunable baseline, not truth.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.measurement.profile import QuantProfile

# ── Thresholds (module-level for auditability + ML-M2 tuning) ────────────────────────────────────
# Durable hypergrowth overrides everything below: an ~8yr average this high is a secular story, not
# a cycle peak or a turnaround — even with a deep COVID/crypto drawdown (NVDA 70%, UBER 34%).
STRONG_GROWER = 0.25

# Distress (turnaround) — persistent: loses money on average, or frequent loss quarters, while NOT
# growing. The growth gate is what separates a real turnaround from a loss-making grower.
DISTRESS_GROWTH_MAX = 0.12   # above this, a lossmaker is a scaling grower, not a turnaround
DISTRESS_LOSS_FREQ = 0.33    # fraction of quarters in the red
DISTRESS_SHRINK = -0.03      # avg TTM revenue growth this negative + thin margins

# Cyclical-commodity — a real peak-to-trough drawdown AND volatile growth (a price-taker), or
# margins that swing hard on their own. (Reached only after the strong-grower override.)
CYC_DRAWDOWN = 0.22
CYC_GROWTH_STD = 0.16
CYC_MARGIN_STD = 0.10

# Platform — high gross margin that is ULTRA-stable (network/aggregator economics). The stability
# cut is what distinguishes GOOGL/META (GMstd 1-2%, OMstd 5-6%) from a high-margin serial acquirer
# like AVGO (GMstd 5%, OMstd 11%). Capex is deliberately NOT gated: modern platforms are capex-heavy.
PLAT_GM_MIN = 0.55
PLAT_GM_STD_MAX = 0.03
PLAT_OM_STD_MAX = 0.08

# Secular grower — durable above-market growth, still scaling (checked after platform).
GROWER_GROWTH_MIN = 0.22

_FINANCIAL_SECTORS = ("financial",)  # substring match, lowercased: "Financial Services"
# Platforms live in tech / communication services. The stability cut alone can't tell a network
# (GOOGL, META) from a high-stable-margin staple (KO ~60% GM, rock-steady) — sector breaks the tie.
# Only gates when sector is known; an unknown sector still allows the margin-based call.
_PLATFORM_SECTORS = ("technology", "communication")
# Commodity-producer sectors. A price-taker here is cyclical even mid-upcycle, so the durable-growth
# override must NOT fire — an E&P or miner averaging >25% growth is riding the commodity, not a
# secular adoption curve (else EQT/gas, gold miners read as "secular growers").
_COMMODITY_SECTORS = ("energy", "materials")


@dataclass
class RuleArchetypeResult:
    archetype: str
    rationale: str
    confidence: str            # high | medium | low
    matched: list[str]         # the signals that fired, for audit


def _pct(x: float | None) -> str:
    return f"{x * 100:.0f}%" if x is not None else "n/a"


def _is_financial(sector: str | None, industry: str | None) -> bool:
    blob = f"{sector or ''} {industry or ''}".lower()
    return any(s in blob for s in _FINANCIAL_SECTORS) or "bank" in blob or "insurance" in blob


def classify_archetype_rules(
    profile: QuantProfile, sector: str | None = None, industry: str | None = None
) -> RuleArchetypeResult:
    """Deterministically assign one of the 6 archetypes from the measured quant profile.

    Mirrors the LLM prompt's discriminators; checked most-specific-first. `sector`/`industry`
    (yfinance text) only break the `financial` case the margin reads can't see.
    """
    p = profile
    g_mean, g_std, drawdown = p.revenue_growth_mean, p.revenue_growth_std, p.revenue_max_drawdown
    gm_mean, gm_std = p.gross_margin_mean, p.gross_margin_std
    om_mean, om_std, nm_mean = p.operating_margin_mean, p.operating_margin_std, p.net_margin_mean
    loss = p.loss_quarter_pct

    # Data completeness drives confidence: a thin profile is a weak provisional label.
    confidence = "high" if p.n_quarters >= 16 else "medium" if p.n_quarters >= 10 else "low"
    matched: list[str] = []

    # 1) Financial — balance-sheet economics; the margin reads don't apply.
    if _is_financial(sector, industry):
        matched.append(f"sector={sector!r}")
        return RuleArchetypeResult(
            "financial",
            f"Sector {sector or '?'} / {industry or '?'} — balance-sheet-driven; classified on the "
            f"business, not margins.",
            confidence, matched,
        )

    # 2) Durable hypergrowth — overrides cyclicality + loss-history. An ~8yr average this high is a
    #    secular story even with a deep drawdown (NVDA) or a lossmaking past (UBER) — UNLESS it's a
    #    commodity producer, where fast growth is just the commodity, not secular adoption.
    commodity_sector = sector is not None and any(s in sector.lower() for s in _COMMODITY_SECTORS)
    if g_mean is not None and g_mean >= STRONG_GROWER and not commodity_sector:
        matched.append(f"avg revenue growth {_pct(g_mean)} (durable, ~{p.n_quarters // 4}yr)")
        return RuleArchetypeResult(
            "secular-grower",
            f"Durable hypergrowth (avg {_pct(g_mean)}) — secular adoption, not a cycle or turnaround.",
            confidence, matched,
        )

    # 3) Deep-value-turnaround — persistent distress while NOT growing (else it's a scaling grower).
    not_growing = g_mean is None or g_mean < DISTRESS_GROWTH_MAX
    distress = []
    if not_growing and om_mean is not None and om_mean <= 0.0:
        distress.append(f"avg operating margin {_pct(om_mean)} on flat/declining revenue")
    if not_growing and loss is not None and loss >= DISTRESS_LOSS_FREQ:
        distress.append(f"{_pct(loss)} of quarters in the red, not growing")
    if (g_mean is not None and g_mean <= DISTRESS_SHRINK
            and nm_mean is not None and nm_mean <= 0.03):
        distress.append(f"revenue shrinking ({_pct(g_mean)} avg) on thin/negative margins")
    if distress:
        matched += distress
        return RuleArchetypeResult(
            "deep-value-turnaround",
            "Persistent distress: " + "; ".join(distress) + ". Thesis is recovery, not growth.",
            confidence, matched,
        )

    # 4) Cyclical-commodity — deep drawdown + volatile growth (price-taker), or margins that swing
    #    hard. Profitable on average and not hypergrowth (those were caught above) — a real cycle.
    deep_dd = drawdown is not None and drawdown >= CYC_DRAWDOWN
    vol_growth = g_std is not None and g_std >= CYC_GROWTH_STD
    vol_margin = gm_std is not None and gm_std >= CYC_MARGIN_STD
    if (deep_dd and vol_growth) or vol_margin:
        if deep_dd:
            matched.append(f"peak-to-trough revenue drawdown {_pct(drawdown)}")
        if vol_growth:
            matched.append(f"growth volatility (std) {_pct(g_std)}")
        if vol_margin:
            matched.append(f"gross-margin swing (std) {_pct(gm_std)}")
        return RuleArchetypeResult(
            "cyclical-commodity",
            "Commodity-cycle economics: " + ", ".join(matched) + ". Margins expand and collapse "
            "with the cycle.",
            confidence, matched,
        )

    # 5) Platform — high gross margin that barely moves (network/aggregator moat), in a sector where
    #    platforms actually live (else a steady high-margin staple reads as one).
    sector_ok = sector is None or any(s in sector.lower() for s in _PLATFORM_SECTORS)
    if (sector_ok
            and gm_mean is not None and gm_mean >= PLAT_GM_MIN
            and gm_std is not None and gm_std <= PLAT_GM_STD_MAX
            and om_std is not None and om_std <= PLAT_OM_STD_MAX):
        matched += [f"gross margin {_pct(gm_mean)} (std {_pct(gm_std)}, ultra-stable)",
                    f"operating-margin std {_pct(om_std)}"]
        return RuleArchetypeResult(
            "platform",
            "High, ultra-stable margins: " + ", ".join(matched) + " — network/aggregator economics.",
            confidence, matched,
        )

    # 6) Secular grower — durable above-market growth, still scaling (moderate band).
    if g_mean is not None and g_mean >= GROWER_GROWTH_MIN:
        matched.append(f"avg revenue growth {_pct(g_mean)}")
        return RuleArchetypeResult(
            "secular-grower",
            f"Durable above-market growth (avg {_pct(g_mean)}), still scaling.",
            confidence, matched,
        )

    # 7) Mature-compounder — the steady-state default: moderate growth, stable margins, shallow cycle.
    matched.append(f"avg growth {_pct(g_mean)}, drawdown {_pct(drawdown)}, GM {_pct(gm_mean)}")
    return RuleArchetypeResult(
        "mature-compounder",
        f"Steady-state economics: moderate growth ({_pct(g_mean)}), shallow drawdown "
        f"({_pct(drawdown)}), stable margins ({_pct(gm_mean)}).",
        "low" if confidence == "medium" else confidence, matched,
    )
