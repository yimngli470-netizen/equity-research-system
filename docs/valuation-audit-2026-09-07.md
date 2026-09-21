# Valuation audit — 2026-09-07

The existing targets have both conservative modeling choices and implementation defects. NVDA's $148.49 should not currently serve as a standing entry threshold. The repair should establish consistent dates, accounting, earnings periods, and valuation assumptions before changing the headline number.

Scope: read the running local database and current source; inspected all 15 latest stored price targets and forecasts; traced NVDA in detail. Reproduced all 24 NVDA quarterly projections exactly using the repository's compiler and reproduced both headline targets to the displayed cent. No application code, database records, or model assumptions were changed. No analysis LLM calls were made. The sensitivity results below are diagnostic calculations on the old snapshot, not updated investment recommendations.

## What the displayed NVDA numbers represent

| Item | Saved value | Date / meaning |
|---|---:|---|
| GAAP target | $148.49 | Target calculated June 30, 2026 |
| Operating target, labeled “Non-GAAP” | $138.54 | Same target date |
| Forecast inputs | — | June 16, 2026; latest actual quarter April 26 |
| Price used for the displayed target upside | $194.97 | Price captured with June 30 target |
| Street target beside the model target | $301.62 | Captured with June 30 target |
| Valuation agent's base DCF estimate | $245 | June 30 report; separate assumptions/calculation |
| Latest price stored in the local database | $217.55 | August 28, not a live quote |
| Latest street mean stored in valuations | $323.42 | August 31, not a live consensus refresh |

The target's displayed -23.84% is relative to the old $194.97 price. Against the latest stored $217.55 it is -31.74%. The local financials already contain the July 26 quarter, so the June forecast is materially out of date. A target originally looking twelve months ahead from June should also carry its fixed target date; it is not automatically a fresh twelve-month target in September.

The arithmetic behind the GAAP target is:

| Scenario | Probability | DCF today | Multiple value today | 60% DCF + 40% multiple |
|---|---:|---:|---:|---:|
| Bear | 26% | $71.14 | $102.66 | $83.75 |
| Base | 46% | $119.07 | $164.25 | $137.14 |
| Bull | 28% | $144.15 | $202.07 | $167.32 |

Probability-weighted fair value is $131.709. Multiplying by 1.1274, the stored cost-of-equity uplift, gives $148.49. The operating calculation similarly increases $122.88 to $138.54. Scenario table values are present fair values, while the headline is labeled as a twelve-month target.

## Confirmed defects

### 1. Valid operating margins are silently capped at 60%

`backend/app/forecast/model.py:28` caps every company at a 60% operating margin. NVDA's raw base assumptions are 65.5%, 65%, 64.5%, 64%, 63.5%, 63%, 62.5%, and 62%. Every base quarter is compiled at 60%, although the saved rationale still describes margins in the mid-60s. The same happens to all bull quarters and the first three bear quarters: 19 of 24 projections are affected. MU also has 14 raw scenario-quarter margins above the cap.

Restoring only NVDA's original margin assumptions, holding other inputs fixed, changes:

| Quantity | Stored | Raw margins restored |
|---|---:|---:|
| Base next-four-quarter EPS | $9.448 | $10.185 |
| Base DCF today | $119.07 | $121.53 |
| Weighted GAAP target | $148.49 | $157.14 |
| Weighted operating target | $138.54 | $146.31 |

This is a real downward distortion, but it explains only part of the overall gap. The relatively small DCF change also reflects the model's formula: raising year-one earnings more than year-two earnings reduces the measured exit growth used to extrapolate later years.

### 2. The “peer” multiple is effectively a broad-universe multiple

`backend/app/valuation_model/target.py:132` selects every `PeerWeight.peer`, ignores the similarity weight, and takes an unweighted median of available forward P/Es, including the stock itself. It applies no industry, archetype, or freshness filter. The peer-weight table is generated for every pair in the universe, rather than just a curated set of economically comparable businesses.

NVDA currently has 597 peer rows, including airlines, utilities, banks, and retailers. Using the current membership list and valuations available through June 30 yields 505 valid multiples including NVDA, with median 17.384808x, which reproduces the stored anchor. Peer membership/weights are overwritten over time, so this reconstruction is not proof that the exact historical membership was identical.

June targets for NVDA, AVGO, ISRG, META, INTU, UBER, and TTD all use a base multiple rounded to 17.4x. Many later targets use 16.2x. The growth tilt only changes bear/bull multiples relative to each company's base scenario; it gives the base case no adjustment for growing faster than its alleged peers.

Diagnostic sensitivities, changing only NVDA's base multiple under the existing formula:

| Assumed base multiple | GAAP target |
|---|---:|
| Stored 17.384808x | $148.49 |
| Illustrative 25x | $179.86 |
| Illustrative 30x | $200.46 |

25x and 30x are sensitivities, not endorsed multiples. A defensible multiple needs comparable businesses, consistent earnings definitions and periods, growth, profitability, and risk justification.

### 3. Earnings periods are not consistently identified

The model calls the next four forecast quarters “NTM.” The June NVDA forecast has $9.448 for those quarters and $12.202 for the following four. The provider's June forward EPS is $12.76443, identical to the saved `+1y` consensus value, and its forward P/E is 15.274478x.

Applying a multiple based on a later earnings denominator to earlier earnings can manufacture apparent downside. As a diagnostic example, 15.274478 x $9.448 = $144.31, while 15.274478 x $12.202 = $186.38. Neither calculation is a new target; they illustrate why the denominator matters. Exact comparable periods must be established before interpreting any EPS divergence.

The ingestion code compounds this: `backend/app/ingestion/estimates_yf.py:27` converts `0y` and `+1y` into latest-filed-quarter-end plus 12 and 24 months. It does not preserve the original period category in the estimate row. A fiscal-year estimate is not the same thing as a rolling twelve-month estimate. Annual and quarterly rows are subsequently selected together by date. For example, the saved June annual estimates are dated April 2027 and April 2028 even though NVIDIA's fiscal year ends around January.

Comparative multiples require the same earnings definition for the subject and comparables. [Damodaran, Relative PE Ratios](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/relpe.htm)

### 4. “Non-GAAP” does not represent company-reconciled adjusted earnings

`backend/app/valuation_model/target.py:259` constructs the operating earnings base as projected GAAP operating income x 79%, using a fixed 21% tax rate. It does not ingest or forecast NVIDIA's actual GAAP-to-non-GAAP reconciliation. It still uses GAAP operating expenses and applies an equity P/E to an after-tax operating-income-per-share proxy.

NVIDIA's own non-GAAP reporting adjusts specific acquisition-related costs, investment gains/losses, other items, and associated taxes. Starting in FY2027 its non-GAAP measures include stock compensation. Its latest guidance gives a 16–18% tax range. Thus neither a generic stock-compensation addback nor a universal 21% NOPAT proxy establishes comparable adjusted EPS. [NVIDIA Q2 FY2027 release](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Second-Quarter-Fiscal-2027/default.aspx)

The operating view can be useful, but should be named accurately. The GAAP view also projects net income via one scenario-level net-income/operating-income factor rather than a full tax and non-operating-income bridge.

### 5. The UI omits the target's essential dates

`backend/app/api/decision.py:150` returns target values and saved upside but omits the target as-of date, forecast date, and reference price. The current page can therefore juxtapose newer market information with old analysis without enough context to reconcile them.

The pull-based refresh policy is intentional; the defect is presenting the old analysis without those dates and its stale status. Re-running the model today would address freshness but retain the structural defects above.

## Modeling choices requiring an explicit decision

### 6. The twelve-month target is a valuation carry-forward shortcut

`backend/app/valuation_model/target.py:318` calculates today's weighted fair value x (1 + cost of equity). It does not explicitly model the terminal price at the target date using the earnings window investors would then be valuing.

For NVDA, the stored base multiple leg is $9.448 x 17.384808 = $164.25. The current carry-forward method takes that leg to $185.18. Applying the same multiple to the following four modeled quarters gives $12.202 x 17.384808 = $212.13 at that later horizon. Exact calendar alignment still matters because the model quarters start from the last reported quarter, not the target calculation date.

A horizon-based exit price and today's intrinsic value are distinct outputs. The exit multiple needs its own justification; using later earnings does not justify also applying a blanket cost-of-equity uplift. Rolling a DCF forward also requires consistent treatment of distributions and retained cash before the target date.

### 7. The DCF forces a short transition to mature growth

`backend/app/valuation_model/dcf.py:128` forecasts two years explicitly, then mechanically fades earnings growth to the terminal rate by year five. NVDA's stored base earnings growth is approximately 28.2% in year two, 19.8% in year three, 8.6% in year four, and 3% in year five. The bull case also reaches 3% in year five. The discount rate stays about 12.73% throughout.

That combination is conservative relative to a longer growth-duration thesis. It is a declared generic rule, not a conclusion demonstrated from NVIDIA's competitive position. It should be visible and scenario-specific. A longer duration must still be justified, rather than selected to match the market.

### 8. The cash-flow/discount-rate framework needs accounting consistency

Historical free cash flow is operating cash flow less capex. The GAAP path scales net income into that cash flow, discounts at WACC, labels the result enterprise value, and subtracts net debt. The operating path uses NOPAT, but calibrates its cash conversion from the same reported cash-flow series. These steps do not establish a clean unlevered FCFF model or a clean FCFE model.

Use explicit FCFF with WACC and the enterprise-to-equity bridge, or explicit FCFE with cost of equity and a consistent equity bridge. The net effect of the current mismatch need not be downward for every stock; NVDA's small debt weight at the old valuation date makes this a secondary explanation for its gap. [Damodaran, Approaches to Valuation](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/approach.html)

Related limitations: the bridge includes cash equivalents but no explicit separately valued marketable securities/investments; the operating multiple uses a static share count while GAAP forecast EPS uses projected shares. These should be reconciled in a common accounting model.

### 9. The AI agent's $245 is a separate, unreconciled model

The June valuation report specifies WACC 11.5%, terminal growth 4%, a 45% FCF margin, and five-year revenue growth of 55%, 30%, 22%, 18%, and 14%. The deterministic model uses different cash flows, 12.73% WACC, 3% terminal growth, and growth already down to 3% in year five.

`backend/app/agents/valuation_agent.py` asks the LLM to emit both assumptions and intrinsic values. Its postprocessing checks percentage formatting and divergence from the street, not the DCF arithmetic. The report lacks a complete cash-flow schedule and explicit starting revenue/share/asset bridge sufficient to reproduce $245 unambiguously.

Changing only the deterministic base DCF's WACC and terminal growth to the agent's 11.5% and 4% increases it from $119.07 to $153.41, still well below $245. Growth duration and cash-flow construction account for additional differences; $245 should not be treated as an independently verified benchmark.

The running decision API simultaneously returns STRONG_BUY and a target with downside. `backend/app/decision/engine.py:325` calculates the target after the signal gates; the target does not bind that signal or sizing. This explains how contradictory outputs survive together.

## Implications and repair order

13 of the 15 latest stored GAAP targets are below their own prices at calculation time. Their dates differ, and several forecasts are old. This supports investigating shared assumptions, but does not establish that every stock is undervalued or that every target must be raised.

1. Correct the margin cap and surface all material assumption adjustments. Version the forecast compiler so a mechanical fix cannot silently reuse old compiled projections.
2. Preserve quarterly/fiscal/rolling period type, actual fiscal dates, estimate as-of date, and GAAP/adjusted basis. Recompute comparisons only when those dimensions align.
3. Replace the universe median with an economically justified comparable set and weighting scheme; show constituents, dates, exclusions, and implied multiple.
4. Rename the operating proxy and establish consistent cash-flow, tax, share-count, and enterprise/equity treatment. Add a real adjusted-EPS reconciliation only when supported by source data.
5. Separate present intrinsic value from a dated twelve-/eighteen-month scenario exit price. Let the LLM explain assumptions and evidence; run all valuation arithmetic through one calculator.
6. Display the target/forecast dates and reference price, and explicitly flag unresolved disagreement between valuation, AI reasoning, and the decision.

For investment use, each scenario should answer: business outcome, earnings at a named period, defensible exit multiple, price at a named horizon, return from a dated current price, and evidence that would invalidate the scenario. A reverse valuation can show what growth, margins, and duration the market price requires.

A price far below the market can be a useful risk assessment if supported by a specific thesis. It is not automatically a likely future trading price or a permanent buy order. A lower market price should trigger a fresh check of earnings, competitive position, financing, and required returns before treating the old valuation as an opportunity.

## User requirement — company-specific economics (2026-09-07)

The valuation repair must distinguish companies such as AMD and AAPL using their business economics and forward outlook. The AMD example assumes stronger near-term growth and a smaller market capitalization; it is a design requirement, not a fresh assessment of either stock. The existing archetype labels provide a starting policy, not a complete valuation model.

### Method selection and assumptions

| Business characteristics | Valuation emphasis | Assumptions that need explicit support |
|---|---|---|
| Profitable company with rapid expected growth and changing product mix, such as the user's AMD example | Earnings at the target horizon, comparable growth/profitability, and DCF with an explicit growth-duration scenario | Segment demand, revenue growth, operating leverage, dilution, competitive share, reinvestment, and how long excess growth lasts |
| Established cash-generating business, such as the AAPL example | Sustainable cash flow and earnings, capital returns, and earnings/cash-flow multiples for comparable businesses | Product/services mix, growth durability, margins, buybacks versus dilution, reinvestment, and balance sheet |
| Commodity cyclical, such as the existing MU archetype | Through-cycle earning power and cycle scenarios | Capacity, pricing, current cycle position, normalized margins, and the duration of excess earnings |
| Loss-making or transitioning business | Explicit path to sustainable cash generation; applicable revenue/operating metrics only with profitability support | Breakeven timing, funding needs, dilution, unit economics, and terminal profitability; suppress meaningless P/E |
| Financial business | Financial-sector methods using equity, profitability, and distributions | Sustainable ROE, capital requirements, credit losses, and cost of equity; do not force an industrial-company enterprise DCF |

These are method-selection principles. Individual methods require supported inputs before implementation. A missing earnings or cash-flow basis should produce a visible coverage limitation, rather than an invented fallback target.

The same calculator can serve multiple businesses, but it must accept different evidence-backed inputs and valuation policies. It should explain both **why this method** and **why these assumptions**. There should be no hardcoded AMD/AAPL branch or preset company price target.

### Deterministic conditioning beneath the labels

- Use forecast revenue and earnings growth, expected margin change, cash conversion, cyclicality, leverage, and dilution to distinguish companies within an archetype. Growth off near-zero or negative earnings requires separate handling; a large percentage alone cannot justify a premium.
- Select economically comparable businesses first. Use business model/industry, growth, profitability, and risk for comparability; use market cap and revenue scale as secondary matching variables. A smaller market cap does not itself demonstrate greater addressable demand or justify a higher multiple. Market cap also changes with the price being evaluated, so it must not become the main valuation anchor.
- Vary the supported high-growth duration and fade path by business and scenario. A fast-growing company should not be forced to mature in year five by a universal rule. Higher growth must carry the associated reinvestment and execution risk; longer duration cannot be a free valuation uplift.
- Compare multiples using the same accounting basis and actual earnings window. GAAP, company-adjusted EPS, and NOPAT are distinct. Model buybacks and dilution consistently with the cash available to fund them.
- For a target at time T, identify the earnings period used to price the business at T and justify the multiple appropriate to its expected growth and risk then. A twelve-month target priced on the subsequent twelve months of earnings requires forecasts through month 24; an eighteen-month target on the same basis requires forecasts through month 30. Do not silently extrapolate beyond available coverage.
- Keep knowledge-laden classifications and supported qualitative assumptions in the existing cached LLM surface. Compute peer weights, cash flows, multiples adjustments, valuations, and sensitivities deterministically from versioned policies and those inputs, following architecture §4a. Distinguish measured relationships from authored policy priors.

### Acceptance criteria for the repair

1. Growth-led and established-business fixtures produce explainable differences in comparable selection, growth duration, and method suitability without ticker-specific code. Sharing an industry or archetype must not force identical valuation assumptions.
2. An AMD-like fixture with supported faster growth can receive different treatment from an AAPL-like fixture; neither a higher multiple nor a higher expected return is guaranteed by its name, size, or growth label.
3. Changing market cap alone cannot create an automatic growth premium. Identical economic assumptions expressed at a different share denomination leave equity value unchanged and per-share value scaled correctly.
4. Hold relevant assumptions fixed when testing sensitivity: improved cash generation should affect value predictably, while changes in growth must expose their reinvestment, dilution, and risk consequences.
5. NVDA's valid operating margins survive compilation; cyclical peak earnings are treated on their appropriate basis; negative earnings do not produce a misleading P/E valuation.
6. Each result exposes its valuation date, target date, earnings period/basis, key drivers, comparable set, method rationale, and uncertainty. Model-versus-street comparisons are only made on compatible definitions.
