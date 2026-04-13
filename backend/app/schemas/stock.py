from datetime import date, datetime

from pydantic import BaseModel


class StockCreate(BaseModel):
    ticker: str
    name: str
    sector: str | None = None
    industry: str | None = None


class StockResponse(BaseModel):
    ticker: str
    name: str
    sector: str | None
    industry: str | None
    added_date: date
    active: bool

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

    model_config = {"from_attributes": True}


class AnalysisReportResponse(BaseModel):
    id: int
    ticker: str
    agent_type: str
    run_date: date
    report: dict
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}
