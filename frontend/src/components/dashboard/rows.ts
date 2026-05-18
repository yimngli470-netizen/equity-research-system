// Unified row shape for the watchlist table and grid.
// Built once from the api responses so both layouts agree on the data.

export interface WatchlistRow {
  ticker: string;
  name: string;
  latest_price: number | null;
  price_change_pct: number | null;
  composite_score: number | null;
  signal: string | null;
  flag_count: number;
  last_run: string | null;
}
