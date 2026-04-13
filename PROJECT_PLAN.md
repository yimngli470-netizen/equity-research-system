# AI-Augmented Equity Research System

## Project Overview

A near-professional-grade equity research platform that combines automated data ingestion, multi-agent AI analysis, quantitative scoring, and rule-based decision signals — all surfaced through a human-friendly dashboard.

---

## System Architecture (6 Layers)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    LAYER 6: FRONTEND / DASHBOARD                    │
│            React + TailwindCSS + Recharts/Tremor                    │
│   Stock selector │ Report viewer │ Score cards │ DCF calculator     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ REST API
┌──────────────────────────────┴──────────────────────────────────────┐
│                     FASTAPI BACKEND (Python)                        │
│              Serves data, triggers analysis, manages state          │
└──┬────────────┬────────────┬─────────────┬─────────────┬───────────┘
   │            │            │             │             │
   ▼            ▼            ▼             ▼             ▼
┌───────┐ ┌─────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐
│Layer 1│ │ Layer 2  │ │ Layer 3  │ │  Layer 4  │ │  Layer 5  │
│Data   │ │   AI     │ │  Quant   │ │  Scoring  │ │ Decision  │
│Ingest │→│ Research │→│  Feature │→│  System   │→│  Engine   │
│       │ │  Agents  │ │  Engine  │ │           │ │           │
└───────┘ └─────────┘ └──────────┘ └───────────┘ └───────────┘
   │            │
   ▼            ▼
┌──────────────────────┐    ┌──────────────────┐
│  PostgreSQL + pgvector│    │   Claude API      │
│  (structured data +   │    │   (Opus/Sonnet)   │
│   document embeddings)│    │                   │
└──────────────────────┘    └──────────────────┘
```

---

## Tech Stack

| Component         | Technology                  | Rationale                                              |
| ----------------- | --------------------------- | ------------------------------------------------------ |
| Backend Framework | FastAPI (Python 3.12+)      | Async, typed, auto-docs, great for concurrent API calls |
| Database          | PostgreSQL + pgvector       | One DB for structured data + vector search              |
| Task Scheduler    | APScheduler or Celery+Redis | Daily ingestion jobs, agent runs                       |
| LLM              | Claude API (Anthropic SDK)  | Superior reasoning for financial analysis, tool use     |
| Embeddings        | Voyage Finance or OpenAI    | For document vectorization (filings, news, transcripts) |
| Frontend          | React + TypeScript          | Component-based, rich ecosystem for dashboards          |
| UI Components     | Tremor or Shadcn/ui         | Pre-built dashboard components (charts, cards, tables)  |
| Charts            | Recharts or Tremor charts   | Financial chart rendering                               |
| ORM               | SQLAlchemy 2.0              | Async Postgres support, migrations via Alembic          |

---

## Layer 1: Data Ingestion (Runs Daily)

### Data Sources

| Data Type              | Source                        | Frequency | Format        |
| ---------------------- | ----------------------------- | --------- | ------------- |
| Price & Volume         | yfinance (free)               | Daily     | Structured    |
| Fundamentals           | yfinance + SEC EDGAR          | Quarterly | Structured    |
| Earnings Transcripts   | SEC EDGAR / Seeking Alpha RSS | Quarterly | Text (→ embed)|
| News                   | NewsAPI / Finnhub             | Daily     | Text (→ embed)|
| Insider Transactions   | SEC EDGAR Form 4              | Daily     | Structured    |
| Industry/Sector Data   | yfinance sector performance   | Daily     | Structured    |
| Analyst Estimates      | yfinance                      | Daily     | Structured    |

### Database Schema (Core Tables)

```sql
-- Portfolio tracking
stocks (ticker, name, sector, industry, added_date, active)

-- Price data
daily_prices (ticker, date, open, high, low, close, volume, adj_close)

-- Fundamental data
financials (ticker, period, period_end_date, revenue, gross_profit, operating_income,
            net_income, eps, free_cash_flow, total_debt, cash, shares_outstanding, ...)

-- Segment-level breakdown
segments (ticker, period, segment_name, revenue, growth_yoy)

-- Earnings events
earnings_events (ticker, report_date, eps_estimate, eps_actual, revenue_estimate,
                 revenue_actual, guidance_direction)  -- 'raise' | 'cut' | 'maintain'

-- Insider activity
insider_trades (ticker, date, insider_name, title, trade_type, shares, price)

-- Documents (for vector search)
documents (id, ticker, doc_type, date, title, content, embedding vector(1536))

-- AI-generated analysis (cached)
analysis_reports (id, ticker, agent_type, run_date, report_json, version)

-- Quant features (computed)
quant_features (ticker, date, feature_name, feature_value, category)

-- Composite scores
stock_scores (ticker, date, growth_score, momentum_score, sentiment_score,
              valuation_score, risk_score, composite_score, signal)
```

### Ingestion Pipeline

```
[Scheduler triggers daily at market close + 1hr]
        │
        ├── fetch_prices(tickers)        → daily_prices table
        ├── fetch_fundamentals(tickers)  → financials table (if new quarter)
        ├── fetch_news(tickers)          → documents table + embeddings
        ├── fetch_insider_trades(tickers)→ insider_trades table
        ├── fetch_earnings_events()      → earnings_events table
        └── fetch_transcripts()          → documents table + embeddings
                │
                ▼
        [Mark ingestion complete → trigger Layer 2]
```

---

## Layer 2: AI Research Agents

Each agent is a specialized Claude API call with:
- A system prompt defining its analyst persona and output schema
- Relevant data pulled from DB and passed as context
- Structured JSON output (validated by Pydantic)

### Agent 1: News Analyst

```
Input:  Latest news articles for {ticker} (from documents table, last 7 days)
System: You are a financial news analyst. For each news item, assess...

Output Schema:
{
  "ticker": "NVDA",
  "analysis_date": "2026-04-12",
  "items": [
    {
      "headline": "...",
      "summary": "...",
      "impact_category": "revenue" | "margin" | "competition" | "regulatory" | "macro",
      "impact_score": 0.0-1.0,
      "impact_direction": "positive" | "negative" | "neutral",
      "reasoning": "...",
      "time_horizon": "short_term" | "medium_term" | "long_term"
    }
  ],
  "overall_news_sentiment": -1.0 to 1.0,
  "key_themes": ["AI demand acceleration", "export controls"]
}
```

### Agent 2: Earnings Analyst

```
Input:  Latest earnings data (financials table) + earnings transcript (vector search)
System: You are a senior earnings analyst. Analyze the quarterly results...

Output Schema:
{
  "ticker": "MU",
  "quarter": "Q2 FY2026",
  "headline_assessment": "Strong beat driven by AI memory demand",
  "key_drivers": [
    {"driver": "HBM3E revenue", "impact": "strong_positive", "detail": "..."}
  ],
  "risks_identified": [
    {"risk": "Consumer DRAM pricing pressure", "severity": 0.6, "detail": "..."}
  ],
  "tone_analysis": {
    "overall_tone": "confident",
    "tone_shift_vs_prior": "more_optimistic",
    "notable_language_shifts": ["'uncertain' → 'accelerating'", "..."]
  },
  "segment_insights": [
    {"segment": "CNBU", "assessment": "...", "growth_outlook": "..."}
  ],
  "guidance_assessment": "raised",
  "earnings_quality_score": 0.0-1.0
}
```

### Agent 3: Industry Analyst

```
Input:  Sector performance data + recent industry news (vector search) +
        company's segment data for context
System: You are an industry/sector analyst specializing in {sector}...

Output Schema:
{
  "ticker": "MU",
  "sector": "Semiconductors",
  "sub_industry": "Memory & Storage",
  "cycle_position": "early_recovery" | "mid_cycle" | "late_cycle" | "downturn",
  "cycle_assessment": "Memory cycle turning positive, HBM driving supercycle...",
  "key_indicators": [
    {"indicator": "DRAM ASP trend", "current_reading": "rising", "signal": "bullish"},
    {"indicator": "Inventory days", "current_reading": "normalizing", "signal": "bullish"}
  ],
  "competitive_position": {
    "market_share_trend": "stable",
    "moat_assessment": "...",
    "key_competitors": ["Samsung", "SK Hynix"],
    "competitive_risks": ["..."]
  },
  "theme_exposures": [
    {"theme": "AI infrastructure", "exposure_score": 0.9, "reasoning": "..."},
    {"theme": "Memory cycle recovery", "exposure_score": 0.85, "reasoning": "..."}
  ]
}
```

### Agent 4: Valuation Analyst

```
Input:  Financials, current price, analyst estimates, sector multiples
System: You are a valuation analyst. Calculate and assess...

Output Schema:
{
  "ticker": "MU",
  "current_price": 108.50,
  "valuation_metrics": {
    "pe_trailing": 22.5,
    "pe_forward": 15.2,
    "ps_trailing": 4.8,
    "ev_sales": 5.1,
    "peg_ratio": 0.8,
    "fcf_yield": 0.045,
    "price_to_book": 2.8
  },
  "dcf_analysis": {
    "assumptions": {
      "revenue_growth_rates": [0.25, 0.18, 0.12, 0.10, 0.08],
      "terminal_growth": 0.03,
      "wacc": 0.10,
      "fcf_margin_assumption": 0.22
    },
    "intrinsic_value_base": 125.00,
    "intrinsic_value_bull": 155.00,
    "intrinsic_value_bear": 90.00,
    "margin_of_safety": 0.15
  },
  "target_price_range": {"low": 95.00, "mid": 125.00, "high": 155.00},
  "valuation_assessment": "moderately_undervalued",
  "valuation_score": 0.0-1.0
}
```

### Agent Orchestration Flow

```
[Ingestion Complete]
        │
        ├── News Agent ─────────────┐
        ├── Earnings Agent ─────────┤
        ├── Industry Agent ─────────┤ (run in parallel via asyncio.gather)
        └── Valuation Agent ────────┘
                                    │
                                    ▼
                    [All reports saved to analysis_reports table]
                                    │
                                    ▼
                            [Trigger Layer 3]
```

---

## Layer 3: Quant Feature Engine

Extracts numerical features from both raw data and AI agent outputs.

### 3.1 Hard Quant Features (from DB)

```python
HARD_QUANT_FEATURES = {
    # Growth
    "revenue_yoy":        lambda f: (f.revenue - f.revenue_prev_year) / f.revenue_prev_year,
    "revenue_qoq":        lambda f: (f.revenue - f.revenue_prev_q) / f.revenue_prev_q,
    "segment_ai_growth":  lambda s: compute_segment_growth(s, "AI"),

    # Profitability
    "gross_margin":       lambda f: f.gross_profit / f.revenue,
    "operating_leverage":  lambda f: f.operating_income_growth / f.revenue_growth,

    # Valuation
    "ev_sales":           lambda f, p: enterprise_value(f, p) / f.revenue_ttm,
    "fcf_yield":          lambda f, p: f.free_cash_flow_ttm / market_cap(f, p),
    "peg_ratio":          lambda f, p: pe_ratio(f, p) / f.eps_growth_rate,

    # Market Behavior
    "momentum_1m":        lambda prices: prices[-1] / prices[-21] - 1,
    "momentum_3m":        lambda prices: prices[-1] / prices[-63] - 1,
    "momentum_12m":       lambda prices: prices[-1] / prices[-252] - 1,
    "volatility_30d":     lambda prices: np.std(daily_returns(prices[-30:])) * np.sqrt(252),
    "relative_strength":  lambda prices, sector_prices: compute_rs(prices, sector_prices),
}
```

### 3.2 Event-Based Features (from DB)

```python
EVENT_FEATURES = {
    "earnings_surprise":   lambda e: (e.eps_actual - e.eps_estimate) / abs(e.eps_estimate),
    "revenue_surprise":    lambda e: (e.revenue_actual - e.revenue_estimate) / e.revenue_estimate,
    "guidance_signal":     lambda e: {"raise": 1.0, "maintain": 0.0, "cut": -1.0}[e.guidance],
    "insider_net_buying":  lambda trades: net_insider_signal(trades, days=90),
}
```

### 3.3 AI-Derived Features (from Agent Outputs)

```python
AI_FEATURES = {
    "news_sentiment":          lambda report: report["overall_news_sentiment"],      # -1 to +1
    "narrative_change_score":  lambda curr, prev: compute_narrative_shift(curr, prev), # -1 to +1
    "risk_score":              lambda report: aggregate_risks(report["risks_identified"]),  # 0-1
    "earnings_quality":        lambda report: report["earnings_quality_score"],       # 0-1
    "tone_shift":              lambda report: encode_tone_shift(report["tone_analysis"]),
    "ai_infra_exposure":       lambda report: find_theme(report, "AI infrastructure"),
    "cycle_sensitivity":       lambda report: find_theme(report, "Memory cycle"),
}
```

---

## Layer 4: Scoring System

### Normalization

All features are normalized to 0–1 scale using category-specific methods:

```python
NORMALIZATION = {
    "growth":      percentile_rank,     # rank among tracked stocks
    "profitability": min_max_scale,     # 0-60% margin → 0-1
    "valuation":   inverse_percentile,  # lower EV/S = higher score
    "momentum":    percentile_rank,
    "sentiment":   shift_scale,         # -1→+1 becomes 0→1
    "risk":        lambda x: 1 - x,    # invert: lower risk = higher score
}
```

### Category Weights (configurable)

```python
DEFAULT_WEIGHTS = {
    "growth":       0.20,
    "profitability": 0.15,
    "valuation":    0.20,
    "momentum":     0.10,
    "sentiment":    0.15,
    "risk":         0.10,
    "event":        0.10,
}
```

### Composite Score Calculation

```python
def compute_composite_score(ticker: str, date: str) -> StockScore:
    features = get_all_features(ticker, date)

    category_scores = {}
    for category, feature_list in CATEGORY_FEATURES.items():
        scores = [normalize(f.value, f.name) for f in feature_list]
        category_scores[category] = weighted_average(scores)

    composite = sum(
        category_scores[cat] * DEFAULT_WEIGHTS[cat]
        for cat in DEFAULT_WEIGHTS
    )

    return StockScore(
        ticker=ticker,
        date=date,
        growth_score=category_scores["growth"],
        momentum_score=category_scores["momentum"],
        sentiment_score=category_scores["sentiment"],
        valuation_score=category_scores["valuation"],
        risk_score=category_scores["risk"],
        composite_score=composite,
        signal=derive_signal(composite, category_scores)
    )
```

### Example Output

```
MU (2026-04-12):
  Growth:       0.80  ██████████████████░░  Strong
  Profitability: 0.65 █████████████████░░░  Above Avg
  Valuation:    0.90  ████████████████████  Cheap
  Momentum:     0.50  ██████████████░░░░░░  Neutral
  Sentiment:    0.70  ██████████████████░░  Improving
  Risk:         0.60  ████████████████░░░░  Moderate
  Event:        0.75  ██████████████████░░  Positive

  ─────────────────────────────────
  Composite:    0.74  → BUY SIGNAL
```

---

## Layer 5: Decision Engine

### Rule-Based Signal Generation

```python
def generate_signal(score: StockScore) -> Decision:
    flags = check_risk_flags(score)

    if score.composite >= 0.75 and score.sentiment >= 0.6 and not flags.major:
        return Decision("STRONG_BUY", "High conviction — strong across all categories")

    elif score.composite >= 0.65 and score.sentiment >= 0.5 and not flags.major:
        return Decision("BUY", "Favorable setup with positive trend")

    elif score.composite <= 0.35 or flags.critical:
        return Decision("SELL", f"Deteriorating fundamentals. Flags: {flags}")

    elif score.composite <= 0.45 and score.sentiment <= 0.4:
        return Decision("REDUCE", "Weakening across multiple categories")

    else:
        return Decision("HOLD", "Mixed signals — monitor closely")
```

### Risk Flag System

```python
RISK_FLAGS = {
    "critical": [
        ("risk_score < 0.2",        "Severe risk factors identified"),
        ("guidance == 'cut'",        "Company cut guidance"),
        ("insider_net_selling > 3",  "Heavy insider selling"),
    ],
    "major": [
        ("sentiment < 0.3 and declining", "Sentiment deteriorating sharply"),
        ("momentum_3m < -0.20",           "Strong negative momentum"),
        ("valuation_score < 0.2",         "Significantly overvalued"),
    ],
    "watch": [
        ("narrative_change < -0.3",  "Narrative shifting negative"),
        ("volatility > 0.6",        "Elevated volatility"),
    ],
}
```

### Example Output

```
┌─────────────────────────────────────────────────┐
│  MU — STRONG BUY                                │
│  Composite: 0.74 │ Confidence: High             │
│                                                  │
│  Thesis:                                         │
│  • Undervalued with improving fundamentals       │
│  • Early memory cycle recovery signal            │
│  • AI/HBM demand providing structural tailwind   │
│                                                  │
│  Risk Flags: None critical                       │
│  Watch: Elevated volatility (0.55)               │
│                                                  │
│  Target Range: $95 – $155 (mid: $125)            │
│  Current: $108.50 → 15% upside to mid-target     │
└─────────────────────────────────────────────────┘
```

---

## Layer 6: Frontend Dashboard

### Tech: React + TypeScript + Tailwind + Tremor (or Shadcn/ui)

### Pages & Components

```
/                         → Portfolio Overview (score cards for all stocks)
/stock/:ticker            → Stock Deep Dive
/stock/:ticker/news       → News Analysis Detail
/stock/:ticker/earnings   → Earnings Analysis Detail
/stock/:ticker/industry   → Industry Analysis Detail
/stock/:ticker/valuation  → Valuation & DCF Calculator
/stock/:ticker/quant      → Feature Breakdown & Score Detail
/compare                  → Side-by-side stock comparison
/signals                  → Decision signals feed (latest buy/sell/hold)
/settings                 → Manage watchlist, weights, thresholds
```

### Portfolio Overview Page

```
┌──────────────────────────────────────────────────────────────┐
│  AI Equity Research Dashboard                    [Settings]  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ NVDA     │ │ MU       │ │ AAPL     │ │ MSFT     │       │
│  │ $925.40  │ │ $108.50  │ │ $198.20  │ │ $445.80  │       │
│  │ +2.3%    │ │ -0.5%    │ │ +1.1%    │ │ +0.8%    │       │
│  │          │ │          │ │          │ │          │       │
│  │ Score:   │ │ Score:   │ │ Score:   │ │ Score:   │       │
│  │ 0.82 ●●● │ │ 0.74 ●●  │ │ 0.61 ●●  │ │ 0.68 ●●  │       │
│  │ STRONG   │ │ STRONG   │ │ HOLD     │ │ BUY      │       │
│  │ BUY      │ │ BUY      │ │          │ │          │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│                                                              │
│  Recent Signals                                              │
│  ├─ MU  → STRONG BUY (was BUY)    Apr 12   Score: 0.74     │
│  ├─ MSFT → BUY (was HOLD)         Apr 11   Score: 0.68     │
│  └─ AAPL → HOLD (unchanged)       Apr 10   Score: 0.61     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Stock Deep Dive Page

```
┌──────────────────────────────────────────────────────────────┐
│  ← Back    MU — Micron Technology       Signal: STRONG BUY  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  [Summary] [News] [Earnings] [Industry] [Valuation] [Quant] │
│                                                              │
│  ┌─ Score Breakdown ──────────────────────────────────────┐  │
│  │ Growth        ████████████████████░░  0.80             │  │
│  │ Profitability ██████████████████░░░░  0.65             │  │
│  │ Valuation     ████████████████████░░  0.90             │  │
│  │ Momentum      ██████████████░░░░░░░░  0.50             │  │
│  │ Sentiment     ██████████████████░░░░  0.70             │  │
│  │ Risk          ████████████████░░░░░░  0.60             │  │
│  │ ──────────────────────────────────                     │  │
│  │ Composite     ██████████████████░░░░  0.74             │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ AI Summary ───────────────────────────────────────────┐  │
│  │ Micron is positioned at an early memory cycle          │  │
│  │ inflection point. HBM3E revenue is accelerating,       │  │
│  │ management tone shifted from cautious to confident...  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ Target Price ─────┐  ┌─ Key Metrics ────────────────┐   │
│  │ Bear:   $95        │  │ P/E (fwd):  15.2x            │   │
│  │ Base:   $125  ◄    │  │ EV/Sales:   5.1x             │   │
│  │ Bull:   $155       │  │ FCF Yield:  4.5%             │   │
│  │ Current: $108.50   │  │ Rev YoY:    +25%             │   │
│  │ Upside:  +15%      │  │ Gross Mrg:  38%              │   │
│  └────────────────────┘  └──────────────────────────────┘   │
│                                                              │
│  ┌─ Interactive DCF Calculator ───────────────────────────┐  │
│  │ Revenue Growth Y1: [25%] ▸  Terminal Growth: [3%]  ▸   │  │
│  │ FCF Margin:        [22%] ▸  WACC:           [10%] ▸   │  │
│  │                                                        │  │
│  │ → Implied Value: $125.00  (15% upside)                 │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
equity-research-system/
├── PROJECT_PLAN.md
├── docker-compose.yml              # Postgres + Redis
├── .env.example                    # API keys template
│
├── backend/
│   ├── pyproject.toml              # Python dependencies (uv/poetry)
│   ├── alembic/                    # DB migrations
│   ├── app/
│   │   ├── main.py                 # FastAPI app entry
│   │   ├── config.py               # Settings (env vars)
│   │   ├── models/                 # SQLAlchemy models
│   │   │   ├── stock.py
│   │   │   ├── price.py
│   │   │   ├── financial.py
│   │   │   ├── document.py
│   │   │   ├── analysis.py
│   │   │   └── score.py
│   │   ├── schemas/                # Pydantic schemas (API + agent outputs)
│   │   │   ├── stock.py
│   │   │   ├── news_analysis.py
│   │   │   ├── earnings_analysis.py
│   │   │   ├── industry_analysis.py
│   │   │   ├── valuation_analysis.py
│   │   │   └── score.py
│   │   ├── ingestion/              # Layer 1
│   │   │   ├── scheduler.py
│   │   │   ├── prices.py
│   │   │   ├── fundamentals.py
│   │   │   ├── news.py
│   │   │   ├── transcripts.py
│   │   │   ├── insider.py
│   │   │   └── embeddings.py
│   │   ├── agents/                 # Layer 2
│   │   │   ├── base.py             # Shared agent logic (Claude API call + retry)
│   │   │   ├── news_agent.py
│   │   │   ├── earnings_agent.py
│   │   │   ├── industry_agent.py
│   │   │   ├── valuation_agent.py
│   │   │   └── orchestrator.py     # Runs all agents for a ticker
│   │   ├── quant/                  # Layer 3
│   │   │   ├── hard_features.py
│   │   │   ├── event_features.py
│   │   │   ├── ai_features.py
│   │   │   └── normalizer.py
│   │   ├── scoring/                # Layer 4
│   │   │   ├── calculator.py
│   │   │   └── weights.py
│   │   ├── decision/               # Layer 5
│   │   │   ├── engine.py
│   │   │   └── risk_flags.py
│   │   └── api/                    # REST endpoints
│   │       ├── stocks.py
│   │       ├── analysis.py
│   │       ├── scores.py
│   │       ├── decisions.py
│   │       └── dcf.py
│   └── tests/
│
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx       # Portfolio overview
│   │   │   ├── StockDetail.tsx     # Deep dive page
│   │   │   ├── Signals.tsx         # Decision feed
│   │   │   ├── Compare.tsx         # Side-by-side comparison
│   │   │   └── Settings.tsx
│   │   ├── components/
│   │   │   ├── ScoreCard.tsx
│   │   │   ├── ScoreBreakdown.tsx
│   │   │   ├── DCFCalculator.tsx
│   │   │   ├── NewsAnalysis.tsx
│   │   │   ├── EarningsReport.tsx
│   │   │   ├── IndustryView.tsx
│   │   │   ├── PriceChart.tsx
│   │   │   └── SignalBadge.tsx
│   │   ├── hooks/
│   │   │   └── useStockData.ts
│   │   └── api/
│   │       └── client.ts           # API client (fetch wrapper)
│   └── tailwind.config.js
│
└── scripts/
    ├── seed_watchlist.py            # Add initial tickers
    └── run_full_pipeline.py         # Manual trigger: ingest → analyze → score
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1-2)
- [ ] Project setup (Python backend, React frontend, Docker Postgres)
- [ ] Database schema + migrations
- [ ] Data ingestion: prices, fundamentals via yfinance
- [ ] Basic API endpoints (CRUD stocks, get prices, get financials)
- [ ] Basic frontend: stock list, price chart, raw metrics table

### Phase 2: AI Agents (Week 3-4)
- [ ] Claude API integration (base agent class with structured output)
- [ ] News Agent (requires news data source setup)
- [ ] Earnings Agent (requires transcript ingestion)
- [ ] Valuation Agent (uses fundamentals data)
- [ ] Industry Agent
- [ ] Agent orchestrator (parallel execution)
- [ ] Frontend: render agent reports on stock detail page

### Phase 3: Quant & Scoring (Week 5-6)
- [ ] Hard quant feature extraction
- [ ] Event-based feature extraction
- [ ] AI-derived feature extraction (from agent outputs)
- [ ] Normalization engine
- [ ] Composite score calculator
- [ ] Frontend: score cards, score breakdown bars, score history chart

### Phase 4: Decision Engine & Polish (Week 7-8)
- [ ] Decision rule engine
- [ ] Risk flag system
- [ ] Signal generation + signal history
- [ ] Interactive DCF calculator (frontend)
- [ ] Stock comparison page
- [ ] Settings page (manage watchlist, adjust weights)
- [ ] Daily scheduler (APScheduler or cron) for full pipeline

### Phase 5: Refinement (Ongoing)
- [ ] Backtest scoring system against historical data
- [ ] Tune weights based on backtesting
- [ ] Add more data sources as needed
- [ ] Improve agent prompts based on output quality
- [ ] Add alerts/notifications for signal changes

---

## API Keys Required

| Service        | Purpose                     | Cost     |
| -------------- | --------------------------- | -------- |
| Anthropic      | Claude API (agent analysis) | Pay/use  |
| NewsAPI        | News articles               | Free tier available |
| yfinance       | Prices + fundamentals       | Free     |
| SEC EDGAR      | Filings + transcripts       | Free     |
| Voyage AI (opt)| Financial embeddings        | Pay/use  |

---

## Key Design Principles

1. **Structured outputs everywhere** — Every agent returns validated JSON via Pydantic. No free-text parsing.
2. **Idempotent pipeline** — Running the pipeline twice for the same date produces the same results. Safe to retry.
3. **Cached analysis** — Agent outputs are stored. Don't re-run expensive LLM calls unless data has changed.
4. **Configurable weights** — Scoring weights are user-adjustable, not hardcoded.
5. **Audit trail** — Every score links back to the features and agent reports that produced it.
