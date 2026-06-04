# How the Analyst Researches a Stock — Methodology & Investment Principles

This document explains, end to end, how the system researches a new name, how it turns that
research into an investment action, and the weighting and principles behind it. It is the "house
view" — the philosophy the code encodes. (For architecture/how-to-run see `CLAUDE.md`; for direction
and progress see `ANALYST_ROADMAP.md`.)

---

## 0. The one-paragraph version

We gather only authoritative, free data (SEC filings, prices, analyst consensus, earnings calls),
**classify the business into an archetype**, run a panel of specialist research agents on the
fundamentals, then stage an **adversarial debate** (bull vs bear) that a **judge** adjudicates into a
calibrated verdict with **dated, falsifiable predictions**. A quantitative **screen** ranks the name
against peers — but the screen is *not* the recommendation. The recommendation comes from the
reasoning, which **caps** the screen: a skeptical or low-conviction judge, or unverifiable evidence,
pulls the action down. Every verdict is journaled and later graded against what actually happened.

The throughline: **measurement gives reproducible numbers; reasoning makes the decision; skepticism
is first-class; every call is accountable.**

---

## 1. The shape of the research

```
DATA          EDGAR financials (10yr) · prices · analyst consensus · earnings transcripts · IR
  │           (every datum carries source + as-of — verifiable)
  ▼
MEASUREMENT   archetype · peer set & closeness · normalized/mid-cycle earnings · cycle position
  │           (deterministic stats — no LLM; the same inputs always give the same numbers)
  ▼
ANALYSIS      news · earnings · industry · valuation agents  (specialist research, one aspect each)
  │
  ▼
DIALECTIC     bull  ⇄  bear   →   judge   (adversarial synthesis; bear is first-class)
  │                                  │
  ▼                                  ▼
SCREEN        7-category composite,        DECISION    judge + evidence gate CAP the screen →
              archetype-weighted →                     final signal + calibrated confidence
              a peer-relative RANK
  │
  ▼
ACCOUNTABILITY   thesis journaled with dated kill-criteria → graded when they come due → calibration
```

Two layers do the work, and keeping them separate is deliberate:
- **Measurement (stats/code):** anything that must be a stable, reproducible number.
- **Reasoning (LLM agents):** knowledge, language, and judgment.

---

## 2. The research agents — what each one investigates

This is the *foundational analysis*: each agent answers one question well, grounded in the data,
and emits a structured report. Eight agents run per name, in order.

### Analytical agents (research the fundamentals)

**1. News agent** — *What just happened, and does it matter?*
Reads recent headlines; scores each item's impact and direction, and an overall sentiment. Captures
catalysts and narrative shifts. → feeds the **sentiment** category.

**2. Earnings agent** — *Are the results good, and getting better or worse?*
Reads the quarterly financial trend + the earnings-call transcript. Assesses earnings quality,
revenue/margin trends, forward outlook, beat/miss history, and management tone. It uses
**pre-extracted, source-cited KPI values** (verbatim from the call) rather than guessing. → feeds
the **event** and **risk** categories.

**3. Industry agent** — *Where is the industry, and how is the company positioned in it?*
Assesses cycle position (early/mid/late/downturn), competitive position (**market-share trend**,
**moat strength**), secular **theme exposure** (AI, cloud, EVs…), and industry-level risks
(cyclicality, regulation, disruption). Grounded in management's own statements where available. →
feeds the **sentiment** and **risk** categories.

**4. Valuation agent** — *What is it worth, and is the price reasonable?*
Runs multiples + a simplified DCF (bull/base/bear), and is **regime-aware**: for a cyclical it
values on **normalized / mid-cycle earnings**, not peak earnings (a low spot P/E on peak earnings is
a trap). It **triangulates** its fair value against the street price target and management guidance,
and must justify any divergence >20%. → feeds the **valuation** category.

### Dialectic agents (turn analysis into a verdict)

**5. Bull agent** — builds the strongest *evidence-cited* case to own the stock; every claim must
rest on a specific number/finding.

**6. Bear agent** — builds the strongest case to avoid/short it, deliberately **first-class** (its
case carries equal standing). It stress-tests the things that usually break a bull thesis: peak
earnings, momentum reversal, what the quant screen misses, competition/secular decline.

**7. Judge** — adjudicates. It **must engage every bear point** (concede / rebut / partial) — it may
not dismiss the bear because momentum or the screen is positive. It outputs a **leaning**
(strong-bull … strong-bear), a **calibrated conviction** (0–1) that must reflect *unresolved* bear
risk, and **≥2 dated, falsifiable kill-criteria** ("Data Center revenue declines QoQ for two
consecutive quarters by Q4 FY2026") with the metric to watch.

### Gate

**8. Validation agent** — cross-checks the analytical agents' quantitative claims against the
database and produces a reliability score. It runs last and acts as an **evidence gate**: if too
many claims are unverifiable/contradicted, a buy cannot ship.

---

## 3. From research to a number — the quant screen

The screen converts the research into a single 0–1 **composite** across seven categories. Each
category is the average of its normalized features; the composite is the **archetype-weighted** sum.

**Where each category comes from:**

| Category | Source | What it captures |
|---|---|---|
| **growth** | financials (code) | revenue/NI/EPS/operating YoY & QoQ, consistency, acceleration |
| **profitability** | financials (code) | gross/operating/net/FCF margins, margin trend, operating leverage |
| **valuation** | 50% multiples (code, **peer-relative**) + 50% valuation agent | cheap/expensive vs peers + the agent's fair-value verdict |
| **event** | earnings agent | earnings quality, forward outlook, beat/miss, management tone |
| **momentum** | prices (code) | 1m / 3m / 12m price momentum |
| **sentiment** | news + industry agents | news tone + industry signal + cycle position |
| **risk** | earnings + industry agents | earnings risk, **industry risk, moat, market-share trend, theme exposure** |

**Crucially, the rulers are peer-relative and the weights are archetype-conditioned.** We do not
judge a memory cyclical and an ad platform on the same scale: valuation multiples are scored as a
percentile *within the peer group*, and each business-model archetype gets its own category weights.

### The weights — explicitly (how much weight on earnings vs industry vs valuation)

Default profile and the per-archetype profiles actually used by the engine (each row sums to 1.0):

| Archetype | growth | profitability | valuation | event | momentum | sentiment | risk |
|---|---|---|---|---|---|---|---|
| **default** | 0.20 | 0.15 | 0.20 | 0.15 | 0.10 | 0.10 | 0.10 |
| cyclical-commodity | 0.15 | 0.20 | 0.12 | 0.15 | **0.05** | 0.08 | **0.25** |
| secular-grower | **0.30** | 0.12 | 0.13 | 0.15 | 0.12 | 0.08 | 0.10 |
| platform | 0.18 | **0.22** | 0.18 | 0.15 | 0.08 | 0.08 | 0.11 |
| mature-compounder | 0.12 | **0.25** | **0.22** | 0.15 | 0.06 | 0.08 | 0.12 |
| financial | 0.10 | 0.20 | **0.22** | 0.15 | 0.08 | 0.08 | 0.17 |
| deep-value-turnaround | 0.10 | 0.13 | **0.27** | 0.15 | 0.07 | 0.08 | 0.20 |

Read against your question — **how much weight on the company's earnings vs the whole industry?** —
the default profile breaks down roughly as:

- **The company's own results & economics ≈ 50%** — growth (0.20) + profitability (0.15) + event
  (0.15). This is the largest block: *what the business is actually doing* dominates.
- **Valuation ≈ 20%** — is the price reasonable for that (peer-relative + agent fair value).
- **Industry, market share, moat, sentiment ≈ 20%** — the industry agent's contribution to **risk**
  and **sentiment**, plus cycle position. Industry is a *context and risk* input, not the lead.
- **Price momentum ≈ 10%** — confirmation, deliberately small.

And the weights *shift by business model*, which is the point:
- For a **cyclical** (MU): momentum is nearly muted (0.05 — a peak run is a trap, not a buy signal),
  spot valuation is down-weighted (0.12 — spot multiples mislead at the peak), and **risk leads at
  0.25**. A current earnings *beat* is deliberately **not** rewarded extra, because a beat at the
  cycle peak is a warning.
- For a **secular-grower**, growth leads (0.30).
- For a **mature-compounder / platform**, profitability and valuation discipline lead.

> These are **documented expert priors** today. The roadmap (§4a) replaces them with weights *learned*
> from a backtest panel once enough graded outcomes accumulate.

---

## 4. From the screen to an action — the decision

**The composite is a SCREEN RANK, not the recommendation.** It tells you where a name sorts against
its peers; it is deliberately *not* presented as "buy this." Treating a weighted average as an oracle
is exactly the failure mode we designed against.

The action comes from the **decision engine**, which is **reasoning-led**:

1. Start from the screen's signal (STRONG_BUY … SELL).
2. **Risk flags** can cap/downgrade it (critical risks cap at HOLD).
3. **The judge binds it.** A bearish or low-conviction judge *caps* the signal — conviction < 0.5
   forbids a STRONG_BUY; bear/neutral caps at HOLD. The judge can only ever **lower** the signal.
4. **The evidence gate binds it.** If validation found the claims largely unverifiable/contradicted,
   a buy is capped to HOLD at low confidence.
5. The result is the **final signal + a calibrated confidence**, with the reasoning written out.

So the qualitative debate isn't a fixed percentage of a blend — it **overrides** the screen. The
screen surfaces and ranks; the reasoning decides; the evidence quality and conviction gate the
result.

### Worked example — Micron (MU), the case the system was built around

| Layer | Output |
|---|---|
| Quant screen | 0.82 → **STRONG_BUY** (growth, momentum, event all near max — peak-cycle signals) |
| Valuation agent | fair value **~$520, overvalued**; normalized P/E 114× vs spot 44.7× ("peak-earnings illusion"); **−23% vs the $674 street, justified** |
| Dialectic | judge leans bull but **conviction ~0.5**, concedes momentum exhaustion + peak margins; engages every bear point |
| **Decision** | **capped to BUY (or HOLD) at moderate confidence** — the screen's enthusiasm is overruled by the reasoning |
| Accountability | thesis journaled: fair value $520 vs price $751, with dated kill-criteria (e.g. "guides Q4 revenue < $30B by 2026-07-15") |

The screen liked MU; the *analyst* did not get carried away — because skepticism and normalized
earnings are wired into the verdict, not quarantined.

---

## 5. Investment principles

These are the convictions the system encodes — the "why" behind the mechanics.

1. **One ruler does not fit every business.** Classify the business model first; judge valuation,
   growth, and risk on archetype- and peer-relative scales, never one absolute yardstick.
2. **The business's own results lead; industry is context and risk.** ~half the screen is the
   company's actual growth, margins, and earnings quality; industry/market-share/moat shape the risk
   and the durability of those results, not the headline.
3. **Value cyclicals on mid-cycle earnings, not peak.** A low multiple on peak earnings is a trap.
   Normalize, and ask explicitly: re-rate or peak illusion?
4. **Skepticism is first-class.** The bear case carries equal standing and cannot be down-weighted;
   the judge must engage every bear point. Most blow-ups come from ignored, not unknown, risks.
5. **Measurement vs. reasoning are separate jobs.** Reproducible numbers come from code; knowledge
   and judgment come from the LLM. Never let the model invent a number that should be measured.
6. **The screen ranks; the reasoning decides.** A composite score is a candidate-surfacing tool, not
   a recommendation. The qualitative verdict overrides it and can only make it more cautious.
7. **Claims must be verifiable.** Every quantitative assertion cites a primary source; a thesis built
   on unverifiable claims cannot ship as a confident buy.
8. **Conviction is calibrated and it binds.** Confidence reflects *unresolved* risk, and low
   conviction caps the action. We would rather be honestly uncertain than falsely precise.
9. **Triangulate, and justify divergence.** Reconcile our fair value against the street and
   management guidance; a large gap must carry a defensible argument, not silence.
10. **Every verdict is falsifiable and accountable.** Each thesis states ≥2 dated, falsifiable
    predictions, is journaled immutably, and is graded against reality when it comes due — so the
    track record (and calibration) is earned, not asserted.
11. **Free, authoritative, auditable data only.** Filings over vendors; provenance on every datum.

---

## 6. Accountability — how the strategy improves

A verdict is a **bet on the record**, not a one-off opinion:

- **Journal (3.1):** every run snapshots the verdict — leaning, conviction, fair value vs price, and
  the dated kill-criteria — immutably.
- **Grade (3.2):** when a prediction's date passes, it is scored hit/miss/partial against the data
  that actually arrived, plus the realized price return. (Runs on the pipeline, not a scheduler.)
- **Calibrate (3.3, planned):** aggregate graded outcomes into a reliability curve *per archetype* —
  the literal test of "when it says 80%, is it right 80%?" Over time this is what tells you which
  archetypes and which signals to trust, and feeds the *learned* weights that replace today's priors.

This is the loop that turns a pile of agent reports into a discipline: research → debate → calibrated
verdict → falsifiable predictions → graded outcomes → better weights → better research.
