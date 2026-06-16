const API_BASE = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `Request failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export interface Stock {
  ticker: string;
  name: string;
  sector: string | null;
  industry: string | null;
  added_date: string;
  active: boolean;
  archetype: string | null;
  latest_price: number | null;
  price_change_pct: number | null;
}

export interface ScreenRank {
  ticker: string;
  archetype: string | null;
  composite_score: number;
  signal: string;
  rank: number;
  total: number;
  archetype_rank: number;
  archetype_total: number;
}

export interface DailyPrice {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adj_close: number;
  volume: number;
}

export interface StockScore {
  ticker: string;
  date: string;
  growth_score: number;
  profitability_score: number;
  valuation_score: number;
  momentum_score: number;
  sentiment_score: number;
  risk_score: number;
  event_score: number;
  composite_score: number;
  signal: string;
  archetype: string | null;
  weights: Record<string, number> | null;
}

export interface AnalysisReport {
  id: number;
  ticker: string;
  agent_type: string;
  run_date: string;
  report: Record<string, unknown>;
  version: number;
  created_at: string;
}

export interface RiskFlag {
  level: string;
  rule: string;
  category: string;
  message: string;
}

export interface Decision {
  ticker: string;
  date: string;
  raw_signal: string;
  raw_composite: number;
  final_signal: string;
  confidence: string;
  risk_flags: RiskFlag[];
  reasoning: string;
  scores: Record<string, number>;
  judge_leaning: string | null;
  judge_conviction: number | null;
  position_sizing: PositionSizing | null;
  price_target: PriceTargetInfo | null;
}

export interface TrackRecordSummary {
  theses_total: number;
  theses_open: number;
  theses_graded: number;
  mean_excess_return: number | null;
  mean_hit_rate: number | null;
  forecasts_total: number;
  forecasts_graded: number;
  forecast_mape: number | null;
  note: string;
}

export interface ThesisRow {
  ticker: string;
  as_of: string;
  archetype: string | null;
  leaning: string | null;
  conviction: number | null;
  decision_signal: string | null;
  price_at: number | null;
  status: string;
  graded_at: string | null;
  hit_rate: number | null;
  realized_return: number | null;
  excess_return: number | null;
  n_kill_criteria: number;
  n_graded_predictions: number;
}

export interface ForecastRow {
  ticker: string;
  as_of: string;
  archetype: string | null;
  base_ntm_eps: number | null;
  base_next_q_eps: number | null;
  street_next_q_eps: number | null;
  eps_vs_street_next_q: number | null;
  status: string;
  mape: number | null;
  n_quarters_resolved: number;
  beat_street: number | null;
}

export interface CalibrationBucket {
  lo: number;
  hi: number;
  n: number;
  mean_conviction: number | null;
  mean_hit_rate: number | null;
  mean_directional: number | null;
}

export interface CalibrationSegment {
  segment: string;
  n_graded: number;
  brier_hit: number | null;
  brier_directional: number | null;
  mean_conviction: number | null;
  mean_directional: number | null;
  overconfidence_gap: number | null;
  buckets: CalibrationBucket[];
}

export interface CalibrationReport {
  overall: CalibrationSegment;
  by_archetype: CalibrationSegment[];
  note: string;
}

export interface ResearchNote {
  ticker: string;
  as_of: string;
  note_md: string;
  changes: string[] | null;
}

export interface PriceTargetInfo {
  fair_value: number | null;
  price_target: number | null;
  horizon_months: number;
  upside: number | null;
  probabilities: Record<string, number | string>;
  // Per-scenario legs: the DCF value vs the multiple value (the spread = the expectations gap).
  scenarios?: Record<string, { dcf: number | null; multiple: number | null; blended: number | null }>;
  method: {
    w_dcf: number;
    multiple_basis: string;
    terminal_growth: number;
    earnings_basis: string;
    // Cyclicals only: our NTM EPS × market fwd P/E — the street's method on OUR earnings.
    forward_multiple_check?: { value: number; ntm_eps: number; fwd_pe: number; note: string } | null;
  };
  wacc: Record<string, number | string>;
  street_target_mean: number | null;
}

export interface PositionSizing {
  action: string;               // accumulate | hold | trim | exit
  target_weight_pct: number;
  current_weight_pct: number;   // what you hold today (6.2)
  delta_pct: number;            // target − current: +add / −trim
  max_weight_pct: number;
  tier: string;                 // none | starter | half | full | max
  multipliers: Record<string, number>;
  rationale: string;
}

export interface BookPosition {
  ticker: string;
  name: string | null;
  sector: string | null;
  archetype: string | null;
  shares: number;
  cost_basis: number | null;
  last_price: number | null;
  market_value: number | null;
  weight: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  beta: number | null;
  opened_date: string | null;
  notes: string | null;
}

export interface Book {
  positions: BookPosition[];
  cash: number;
  total_invested: number;
  total_book: number;
  cash_pct: number;
  n_positions: number;
  sector_weights: Record<string, number>;
  portfolio_beta: number | null;
  top_correlations: { a: string; b: string; corr: number }[];
  total_unrealized_pnl: number | null;
  as_of: string | null;
}

export interface ScreenRow {
  ticker: string;
  name: string;
  sector: string | null;
  archetype: string | null;
  archetype_source: string | null;   // "rules" (provisional) | "llm" (confirmed)
  coverage_tier: string;             // "universe" | "watchlist"
  composite_score: number;
  signal: string;
  as_of: string;
  rank: number;
  total: number;
  archetype_rank: number;
  archetype_total: number;
}

export interface UniverseStatus {
  total_names: number;
  watchlist: number;
  universe: number;
  scored: number;
  constituents_as_of: string | null;
  refresh_job: {
    running: boolean;
    started_at: string | null;
    finished_at: string | null;
    summary: Record<string, number | string> | null;
    error_count?: number;
  };
  promotions: Record<string, { running: boolean; started_at: string | null; finished_at: string | null }>;
}

export interface IngestionResult {
  ticker: string;
  prices: number;
  financials: number;
  valuation: boolean;
  news: number;
  transcripts: number;
  earnings_surprises: number;
  analyst_estimates: number;
  errors: string[];
  warnings: string[];
}

export interface AnalysisRunResult {
  ticker: string;
  ingestion: IngestionResult | null;
  results: {
    agent_type: string;
    success: boolean;
    cached: boolean;
    error?: string | null;
  }[];
  all_succeeded: boolean;
}

export interface ValuationResponse {
  ticker: string;
  date: string;
  forward_pe: number | null;
  trailing_pe: number | null;
  peg_ratio: number | null;
  price_to_sales: number | null;
  price_to_book: number | null;
  ev_to_revenue: number | null;
  ev_to_ebitda: number | null;
  trailing_eps: number | null;
  forward_eps: number | null;
  earnings_growth: number | null;
  revenue_growth: number | null;
  gross_margins: number | null;
  operating_margins: number | null;
  profit_margins: number | null;
  market_cap: number | null;
  enterprise_value: number | null;
  shares_outstanding: number | null;
}

export const api = {
  stocks: {
    list: () => request<Stock[]>('/stocks/'),
    get: (ticker: string) => request<Stock>(`/stocks/${ticker}`),
    add: (data: { ticker: string; name: string; sector?: string; industry?: string }) =>
      request<Stock>('/stocks/', { method: 'POST', body: JSON.stringify(data) }),
    remove: (ticker: string) => request<void>(`/stocks/${ticker}`, { method: 'DELETE' }),
    valuation: (ticker: string) =>
      request<ValuationResponse | null>(`/stocks/${ticker}/valuation`),
  },
  prices: {
    get: (ticker: string, limit = 252) =>
      request<DailyPrice[]>(`/stocks/${ticker}/prices?limit=${limit}`),
  },
  scores: {
    list: (ticker: string) => request<StockScore[]>(`/stocks/${ticker}/scores`),
    latest: (ticker: string) => request<StockScore | null>(`/stocks/${ticker}/scores/latest`),
  },
  analysis: {
    list: (ticker: string, agentType?: string) => {
      const params = agentType ? `?agent_type=${agentType}` : '';
      return request<AnalysisReport[]>(`/stocks/${ticker}/analysis${params}`);
    },
    run: (
      ticker: string,
      options: {
        force?: boolean;
        // 'smart' re-runs an agent only when its inputs changed (new filing/transcript/estimates/
        // material news) — quiet-day pipeline runs cost ~0 LLM calls.
        mode?: 'smart' | 'force' | 'cache';
        ingestFirst?: boolean;
        agentTypes?: string[];
      } = {},
    ) =>
      request<AnalysisRunResult>('/analysis/run', {
        method: 'POST',
        body: JSON.stringify({
          ticker,
          force: options.force ?? false,
          mode: options.mode,
          ingest_first: options.ingestFirst ?? true,
          agent_types: options.agentTypes,
        }),
      }),
  },
  scoring: {
    run: (ticker: string, weights?: Record<string, number>) =>
      request<{
        ticker: string;
        date: string;
        growth_score: number;
        profitability_score: number;
        valuation_score: number;
        momentum_score: number;
        sentiment_score: number;
        risk_score: number;
        event_score: number;
        composite_score: number;
        signal: string;
        feature_count: number;
      }>('/scoring/run', {
        method: 'POST',
        body: JSON.stringify({ ticker, weights }),
      }),
    weights: () =>
      request<{
        weights: Record<string, number>;
        thresholds: Record<string, number>;
      }>('/scoring/weights'),
    screen: () => request<ScreenRank[]>('/scoring/screen'),
    features: (ticker: string) =>
      request<{ feature_name: string; feature_value: number; category: string }[]>(
        `/scoring/features/${ticker}`
      ),
  },
  decision: {
    run: (ticker: string) =>
      request<Decision>('/decision/run', {
        method: 'POST',
        body: JSON.stringify({ ticker }),
      }),
    latest: (ticker: string) => request<Decision | null>(`/decision/${ticker}/latest`),
  },
  trackRecord: {
    summary: () => request<TrackRecordSummary>('/track-record/summary'),
    theses: () => request<ThesisRow[]>('/track-record/theses'),
    forecasts: () => request<ForecastRow[]>('/track-record/forecasts'),
    calibration: () => request<CalibrationReport>('/track-record/calibration'),
  },
  universe: {
    screen: (opts: { archetype?: string; tier?: string; limit?: number } = {}) => {
      const p = new URLSearchParams();
      if (opts.archetype) p.set('archetype', opts.archetype);
      if (opts.tier) p.set('tier', opts.tier);
      if (opts.limit) p.set('limit', String(opts.limit));
      const qs = p.toString();
      return request<ScreenRow[]>(`/universe/screen${qs ? `?${qs}` : ''}`);
    },
    status: () => request<UniverseStatus>('/universe/status'),
    refresh: (body: { refresh_constituents?: boolean; skip_fresh_days?: number; max_names?: number } = {}) =>
      request<{ status: string; note: string }>('/universe/refresh', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    promote: (ticker: string) =>
      request<{ status: string; ticker: string; note: string }>(`/universe/promote/${ticker}`, {
        method: 'POST',
      }),
  },
  portfolio: {
    book: () => request<Book>('/portfolio/book'),
    upsertPosition: (
      ticker: string,
      body: { shares: number; cost_basis?: number | null; opened_date?: string | null; notes?: string | null },
    ) =>
      request<{ ticker: string; removed?: boolean }>(`/portfolio/positions/${ticker}`, {
        method: 'PUT',
        body: JSON.stringify(body),
      }),
    deletePosition: (ticker: string) =>
      request<{ ticker: string; removed: boolean }>(`/portfolio/positions/${ticker}`, { method: 'DELETE' }),
    setCash: (cash: number) =>
      request<{ cash: number }>('/portfolio/cash', { method: 'PUT', body: JSON.stringify({ cash }) }),
  },
  notes: {
    latest: (ticker: string) => request<ResearchNote | null>(`/notes/${ticker}/latest`),
    build: (ticker: string) =>
      request<ResearchNote>('/notes/build', {
        method: 'POST',
        body: JSON.stringify({ ticker }),
      }),
  },
  ingestion: {
    run: (tickers?: string[]) =>
      request<IngestionResult[]>('/ingestion/run', {
        method: 'POST',
        body: JSON.stringify({ tickers }),
      }),
  },
  health: () => request<{ status: string; env: string }>('/health'),
};
