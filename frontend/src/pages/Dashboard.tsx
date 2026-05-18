import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Stock } from '../api/client';
import DashboardHeader from '../components/dashboard/DashboardHeader';
import WatchlistToolbar, { type Layout, type SortBy } from '../components/dashboard/WatchlistToolbar';
import WatchlistTable from '../components/dashboard/WatchlistTable';
import WatchlistGrid from '../components/dashboard/WatchlistGrid';
import type { WatchlistRow } from '../components/dashboard/rows';
import { fmtRelativeTime } from '../components/primitives/format';

const LAYOUT_KEY = 'watchlist-layout';
const SORT_KEY = 'watchlist-sort';

function loadLayout(): Layout {
  const v = localStorage.getItem(LAYOUT_KEY);
  return v === 'grid' ? 'grid' : 'table';
}
function loadSort(): SortBy {
  const v = localStorage.getItem(SORT_KEY);
  if (v === 'ticker' || v === 'change' || v === 'flags' || v === 'score') return v;
  return 'score';
}

export default function Dashboard() {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [rows, setRows] = useState<WatchlistRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState('');
  const [sortBy, setSortByRaw] = useState<SortBy>(() => loadSort());
  const [layout, setLayoutRaw] = useState<Layout>(() => loadLayout());

  const setLayout = (v: Layout) => {
    setLayoutRaw(v);
    localStorage.setItem(LAYOUT_KEY, v);
  };
  const setSortBy = (v: SortBy) => {
    setSortByRaw(v);
    localStorage.setItem(SORT_KEY, v);
  };

  useEffect(() => {
    loadAll();
  }, []);

  async function loadAll() {
    try {
      setLoading(true);
      const data = await api.stocks.list();
      setStocks(data);

      // For each stock, fetch latest score + decision in parallel.
      // N+1 query — acceptable for a personal watchlist of ~10 stocks.
      const enriched = await Promise.all(
        data.map(async (s): Promise<WatchlistRow> => {
          const [score, decision] = await Promise.all([
            api.scores.latest(s.ticker).catch(() => null),
            api.decision.latest(s.ticker).catch(() => null),
          ]);
          return {
            ticker: s.ticker,
            name: s.name,
            latest_price: s.latest_price,
            price_change_pct: s.price_change_pct,
            composite_score: score ? score.composite_score : null,
            signal: decision ? decision.final_signal : score ? score.signal : null,
            flag_count: decision ? decision.risk_flags.length : 0,
            last_run: fmtRelativeTime(decision?.date ?? score?.date ?? null),
          };
        }),
      );
      setRows(enriched);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load watchlist');
    } finally {
      setLoading(false);
    }
  }

  async function handleAdd() {
    const t = window.prompt('Add ticker:');
    if (!t) return;
    const ticker = t.trim().toUpperCase();
    if (!ticker) return;
    try {
      await api.stocks.add({ ticker, name: ticker });
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add stock');
    }
  }

  const filtered = rows.filter((r) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return r.ticker.toLowerCase().includes(q) || (r.name || '').toLowerCase().includes(q);
  });

  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'score') return (b.composite_score ?? -1) - (a.composite_score ?? -1);
    if (sortBy === 'ticker') return a.ticker.localeCompare(b.ticker);
    if (sortBy === 'change')
      return (b.price_change_pct ?? -Infinity) - (a.price_change_pct ?? -Infinity);
    if (sortBy === 'flags') return b.flag_count - a.flag_count;
    return 0;
  });

  return (
    <div>
      <DashboardHeader rows={rows} />

      <WatchlistToolbar
        query={query}
        setQuery={setQuery}
        sortBy={sortBy}
        setSortBy={setSortBy}
        layout={layout}
        setLayout={setLayout}
        onAdd={handleAdd}
      />

      {error && (
        <div
          style={{
            background: 'var(--color-neg-bg)',
            border: '1px solid var(--color-rule)',
            color: 'var(--color-neg-fg)',
            padding: '10px 14px',
            borderRadius: 6,
            fontSize: 12.5,
            marginBottom: 16,
          }}
        >
          {error}{' '}
          <button
            onClick={() => setError(null)}
            style={{
              marginLeft: 8,
              textDecoration: 'underline',
              background: 'transparent',
              border: 'none',
              color: 'inherit',
              cursor: 'pointer',
            }}
          >
            Dismiss
          </button>
        </div>
      )}

      {loading ? (
        <div style={{ color: 'var(--color-ink-3)', fontSize: 13, padding: '40px 0' }}>
          Loading watchlist…
        </div>
      ) : stocks.length === 0 ? (
        <div style={{ color: 'var(--color-ink-3)', fontSize: 13, padding: '40px 0' }}>
          No stocks in your watchlist. Click "+ Add ticker" to get started.
        </div>
      ) : layout === 'table' ? (
        <WatchlistTable rows={sorted} />
      ) : (
        <WatchlistGrid rows={sorted} />
      )}
    </div>
  );
}
