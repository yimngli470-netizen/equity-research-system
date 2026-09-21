# Valuation repair — September 20, 2026

The [original audit](valuation-audit-2026-09-07.md) reproduced the old NVDA target and identified
inconsistent periods, margin clipping, unrelated peers, stale displays, and two independent DCF
calculations. The repaired implementation uses one deterministic calculator, version
`economics-2026-09-20.3`, with forecast compiler `2026-09-20.1`.

## What the prices now mean

| Output | Definition |
|---|---|
| Present DCF | Equity distributions discounted to the calculation date, at cost of equity |
| Scenario target | Share price at a specified future date; future DCF excludes distributions paid before that date |
| Forward-earnings leg | Forecast GAAP EPS for the twelve months after the target date × an eligible comparable P/E |
| Headline target | Probability-weighted bear/base/bull future prices |
| Operating sensitivity | Separate historical operating-earnings-to-cash bridge; not company-reported non-GAAP EPS |
| Street target | Separately dated provider snapshot; not an input used to force the model result |

The default horizon is twelve months; the calculator also supports eighteen months. Forecasts
contain twelve explicit quarters. Partial calendar quarters are prorated and labeled approximate;
incomplete coverage cannot silently extend the forecast.

Archetypes provide starting policies. Forecast growth and profitability determine growth duration
and method emphasis; the growth/margin adjustment applies to the base case as well as bull/bear.
Market capitalization supplies secondary peer context, not an automatic premium. Cyclicals use
normalized earning power. Policy coefficients and neutral 25%/50%/25% scenario weights are declared
priors, not calibrated prediction probabilities.

## Controls that affect the result

- A comparable needs four consecutive reported quarters of earnings, operating income, revenue,
  and shares, positive aggregate earnings, compatible economics, fresh prices, and a complete
  matching GAAP forecast. At least two eligible peers are required. Broad provider software
  classifications cannot establish a business-model match; these use DCF until narrower coverage
  exists. Missing peers never trigger an unrelated-universe or invented multiple fallback.
- Cash conversion uses consecutive historical FCF/earnings, including negative quarters. It is
  a proxy with explicit limits, not a complete reinvestment model. DCF uses cost of equity and
  zero net borrowing; it does not subtract debt a second time or separately add investment assets.
- Share compensation comes from measured SBC/revenue. Desired gross buybacks are
  `max(0, SBC - requested net share issuance × reference price)`. Actual modeled buybacks are capped
  at quarterly FCF, and unmet retirements carry forward as additional shares in every later quarter.
  A warning explains the added dilution; EPS, DCF distributions per share, and the multiple leg are
  recomputed using the funded path. Peer EPS receives the same funding adjustment. The original
  forecast remains intact beside the funded share path and its adjustment audit. A positive-FCF
  company therefore remains evaluable when its requested buybacks are too high. Negative projected
  FCF or an unsupported cash-flow basis remains unavailable; no cash reserves, borrowing, or proceeds
  from share issuance are assumed. The constant buyback reference price and cash-settled terminal-share
  assumption are disclosed.
- The optional operating sensitivity holds the GAAP-funded share path fixed. If its separate cash
  bridge cannot fund that path, it can fail without suppressing a valid GAAP result.
- The valuation agent explains the calculator. It cannot insert a separate mental DCF. Its
  displayed base values come from the same stored model as the decision panel; the headline
  weights all scenarios. Earlier narrative is identified separately and suppressed when inconsistent.
- Version, age, and newer-financial guards hide stale values across the decision panel, agent card,
  and newly compiled research notes. Stored historical reports remain intact.

These are conditional scenarios, not standing buy orders. A substantially lower price calls for
a fresh assessment of the thesis and its inputs. A materially different DCF and comparable value
now produces an explicit warning rather than an unexplained blended price. Existing judge decisions
and position sizes retain their original dates; a valuation refresh does not re-run those decisions.

## Filed-data corrections

Broadcom reports `ProfitLoss`. The previous mapping missed it. The fallback now requires matching
filing and duration, and either explicit noncontrolling-income deduction or reconciliation to
diluted EPS × diluted weighted shares within reported EPS rounding. An available parent net-income
tag takes precedence. The August 2 filing supports the $13.088bn quarterly income and EPS numerator.
[Broadcom 10-Q](https://www.sec.gov/Archives/edgar/data/1730168/000173016826000080/avgo-20260802.htm)

Corning reports capital expenditures under `PaymentsForCapitalImprovements`, now included in the
capex map. Its June 30 filing reports $754m year-to-date; subtracting Q1 produces $422m Q2 capex.
The previous share fallback could take treasury-inclusive issued shares. That fallback is removed.
[Corning 10-Q](https://www.sec.gov/Archives/edgar/data/24741/000002474126000255/glw-20260630.htm)

The starting share denominator uses the greater of filed quarterly diluted shares and period-end
basic outstanding shares as a conservative current-share proxy. It preserves actual issuance while
avoiding treasury-inclusive issued shares. Annual diluted weighted averages cannot safely be
subtracted to invent Q4 diluted shares, so no such denominator is manufactured.

## Verification

- 87 backend tests passed, including the full pipeline integration test, independent per-share
  discounted-cash-flow reconstruction, accounting-period matching, company economics, peer eligibility,
  SBC/buyback funding, input mapping, compiler caching, and stale-report hydration.
- Frontend production build passed (`tsc -b` and Vite).
- API contracts checked across all 17 company decisions; NVDA’s refreshed agent base DCF and
  future target match the stored scenario exactly, with its narrative current under model version .3.
- Estimate period/basis migration is applied at Alembic head `c8e4a72f019d`.
- The final visual browser recheck was unavailable because the host Mac was locked; API checks and
  the production build cover the final integration, but do not replace a visual inspection.

## Portfolio refresh

Financials were refreshed for all 17 active companies, and all 15 companies with sufficient history
have freshly compiled forecasts. Fourteen companies now have complete bear/base/bull valuations.
Prices below use the September 18 close; targets are dated September 20, 2027. Scenario weights
are the declared neutral 25% bear / 50% base / 25% bull prior. These are local research snapshots,
not live quotes or calibrated trading-price probabilities.

| Company | Reference price | Bear | Base | Bull | Weighted target |
|---|---:|---:|---:|---:|---:|
| AVGO | $357.61 | $93.42 | $239.51 | $371.79 | $236.06 |
| GLW | $150.13 | $18.97 | $35.53 | $48.00 | $34.51 |
| GOOGL | $349.54 | $101.38 | $184.35 | $247.58 | $179.41 |
| INTU | $303.19 | $246.72 | $368.77 | $462.87 | $361.78 |
| ISRG | $393.33 | $100.94 | $163.40 | $214.38 | $160.53 |
| META | $665.75 | $203.15 | $397.05 | $575.36 | $393.15 |
| MRVL | $244.25 | $12.20 | $67.66 | $116.33 | $65.96 |
| MSFT | $493.78 | $186.78 | $254.77 | $325.19 | $255.38 |
| MU | $1,015.80 | $76.46 | $114.77 | $217.46 | $130.87 |
| NOW | $135.47 | $38.65 | $60.68 | $78.59 | $59.65 |
| NVDA | $222.27 | $103.69 | $366.90 | $556.55 | $348.51 |
| TSLA | $364.27 | $7.52 | $34.20 | $81.73 | $39.41 |
| UBER | $70.50 | $20.51 | $64.59 | $120.60 | $67.57 |
| VRT | $249.39 | $41.73 | $105.59 | $162.98 | $103.97 |

AVGO, MRVL and NVDA have both DCF and comparable-earnings legs. The other ready names use
DCF alone because eligible comparable coverage or through-cycle history is insufficient.
The full [snapshot](valuation-snapshot-2026-09-20.json) includes present DCF, method warnings,
and funding-adjustment counts. Many DCF-only values remain far below market; those gaps are
unresolved assumptions about business duration, reinvestment and risk, not suggested standing buy orders.

| Company without a weighted target | Remaining limitation |
|---|---|
| FIG | Four financial quarters; insufficient driver history and no supported forecast |
| SPCX | One financial quarter; insufficient driver history and no supported forecast |
| TTD | Bear path projects negative operating FCF; a liquidity/financing model is needed before assigning a complete weighted valuation |

GOOGL, INTU and MRVL remain valued when requested buybacks exceed modeled FCF: the calculator
reduces repurchases and carries the resulting additional shares through EPS and valuation.
INTU’s optional operating sensitivity remains unavailable for one scenario on that same funded
share path; its GAAP valuation is complete. TTD’s operating loss is a separate funding problem,
which cannot be repaired merely by reducing buybacks.

### NVDA reconciliation

The new $348.51 weighted future target combines updated filings, consensus and assumptions with
the model repair. Its reference close is $222.27; the separately dated Street snapshot is $327.70.
The base future target is $366.90: 40% future DCF ($203.21) plus 60% comparable-earnings value
($476.03). The latter uses $18.244 modeled GAAP EPS over September 20, 2027–September 20, 2028
and an adjusted 26.09× multiple. The eligible peer set is AVGO and MRVL and remains thin.

Present base DCF is $186.04; probability-weighted present DCF is $194.98. These values have
different dates and/or method weights from the headline target. The large disagreement between
the DCF and earnings-multiple legs is explicitly flagged. The refreshed valuation-agent explanation
focuses on growth duration, cash conversion, peer coverage and capital allocation, and its numeric
fields are checked against this same stored calculator output.
