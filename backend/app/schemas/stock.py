from datetime import date, datetime

from pydantic import BaseModel


class StockCreate(BaseModel):
    ticker: str
    name: str
    sector: str | None = None
    industry: str | None = None
    # REQUIRED: the company's IR earnings page URL, written straight to the IR registry (no LLM guess).
    # Auto-discovery was removed — IR domains are too often non-obvious (e.g. ISRG → isrg.intuitive.com)
    # for a guess to be reliable. The user pastes the URL when adding a name.
    ir_url: str


class StockResponse(BaseModel):
    ticker: str
    name: str
    sector: str | None
    industry: str | None
    added_date: date
    active: bool
    archetype: str | None = None  # business-model archetype (roadmap 1.1)

    model_config = {"from_attributes": True}


class StockWithLatestPrice(StockResponse):
    latest_price: float | None = None
    price_change_pct: float | None = None


class DailyPriceResponse(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int

    model_config = {"from_attributes": True}


class FinancialResponse(BaseModel):
    ticker: str
    period: str
    period_end_date: date
    revenue: float | None
    gross_profit: float | None
    operating_income: float | None
    net_income: float | None
    eps: float | None
    free_cash_flow: float | None
    operating_cash_flow: float | None
    total_debt: float | None
    cash_and_equivalents: float | None
    total_assets: float | None
    total_equity: float | None
    shares_outstanding: float | None

    model_config = {"from_attributes": True}


class ValuationResponse(BaseModel):
    ticker: str
    date: date
    forward_pe: float | None
    trailing_pe: float | None
    peg_ratio: float | None
    price_to_sales: float | None
    price_to_book: float | None
    ev_to_revenue: float | None
    ev_to_ebitda: float | None
    trailing_eps: float | None
    forward_eps: float | None
    earnings_growth: float | None
    revenue_growth: float | None
    gross_margins: float | None
    operating_margins: float | None
    profit_margins: float | None
    market_cap: float | None
    enterprise_value: float | None
    shares_outstanding: float | None

    model_config = {"from_attributes": True}


class StockScoreResponse(BaseModel):
    ticker: str
    date: date
    growth_score: float
    profitability_score: float
    valuation_score: float
    momentum_score: float
    sentiment_score: float
    risk_score: float
    event_score: float
    composite_score: float
    signal: str
    # The composite is a peer-relative SCREEN RANK, not a verdict (roadmap 1.5). These let the UI
    # show the actual archetype-conditioned weights used (1.4) rather than fixed ones.
    archetype: str | None = None
    weights: dict[str, float] | None = None

    model_config = {"from_attributes": True}


class ScreenRankResponse(BaseModel):
    """Where a name sorts among its peers by composite — the screen-rank framing (roadmap 1.5)."""

    ticker: str
    archetype: str | None
    composite_score: float
    signal: str
    rank: int            # 1 = highest composite in the active watchlist
    total: int
    archetype_rank: int  # rank within its archetype group
    archetype_total: int


class AnalysisReportResponse(BaseModel):
    id: int
    ticker: str
    agent_type: str
    run_date: date
    report: dict
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}
