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
  return res.json();
}

export interface Stock {
  ticker: string;
  name: string;
  sector: string | null;
  industry: string | null;
  added_date: string;
  active: boolean;
  latest_price: number | null;
  price_change_pct: number | null;
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

export const api = {
  stocks: {
    list: () => request<Stock[]>('/stocks/'),
    get: (ticker: string) => request<Stock>(`/stocks/${ticker}`),
    add: (data: { ticker: string; name: string; sector?: string; industry?: string }) =>
      request<Stock>('/stocks/', { method: 'POST', body: JSON.stringify(data) }),
    remove: (ticker: string) => request<void>(`/stocks/${ticker}`, { method: 'DELETE' }),
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
    features: (ticker: string) =>
      request<{ feature_name: string; feature_value: number; category: string }[]>(
        `/scoring/features/${ticker}`
      ),
  },
  health: () => request<{ status: string; env: string }>('/health'),
};
