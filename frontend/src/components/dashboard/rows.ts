// Unified row shape for the watchlist table and grid.
// Built once from the api responses so both layouts agree on the data.

export interface WatchlistRow {
  ticker: string;
  name: string;
  archetype: string | null;
  latest_price: number | null;
  price_change_pct: number | null;
  composite_score: number | null;
  signal: string | null;
  flag_count: number;
  last_run: string | null;
  // Post-earnings notification: set when the company has reported since the earnings agent last
  // ran. Purely informational — the user decides whether to spend the LLM call.
  earnings_alert: { severity: 'reported' | 'transcript'; reason: string } | null;
}
