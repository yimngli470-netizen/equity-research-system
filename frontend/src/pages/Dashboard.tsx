import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Stock } from '../api/client';
import DashboardHeader from '../components/dashboard/DashboardHeader';
import WatchlistToolbar, { type Layout, type SortBy } from '../components/dashboard/WatchlistToolbar';
import WatchlistTable from '../components/dashboard/WatchlistTable';
import WatchlistGrid from '../components/dashboard/WatchlistGrid';
import AddStockModal from '../components/dashboard/AddStockModal';
import type { WatchlistRow } from '../components/dashboard/rows';
import { fmtRelativeTime } from '../components/primitives/format';
import type { PipelineResult } from '../state/pipelineTracker';

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

  const [addOpen, setAddOpen] = useState(false);
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkLabel, setBulkLabel] = useState<string | null>(null);
  const [bulkReport, setBulkReport] = useState<PipelineResult[] | null>(null);
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
    // If a server-side Run All is already in progress (started by this tab before a reload, or by
    // another tab), attach to it and show live progress. The run lives in the backend now.
    api.pipeline
      .runAllStatus()
      .then((s) => {
        if (s.running) pollRunAll();
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
            archetype: s.archetype,
            latest_price: s.latest_price,
            price_change_pct: s.price_change_pct,
            composite_score: score ? score.composite_score : null,
            signal: decision ? decision.final_signal : score ? score.signal : null,
            flag_count: decision ? decision.risk_flags.length : 0,
            last_run: fmtRelativeTime(decision?.created_at ?? decision?.date ?? score?.date ?? null),
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

  // Ticker + required IR URL are collected together in one modal (AddStockModal). Throwing here keeps
  // the modal open and surfaces the message inside it.
  async function submitAdd(ticker: string, irUrl: string) {
    await api.stocks.add({ ticker, name: ticker, ir_url: irUrl });
    await loadAll();
  }

  // Poll the server-side Run All until it finishes, mirroring its progress into the bulk UI. The
  // loop runs in the backend (survives tab close); this only reflects status, so closing/reopening
  // the dashboard mid-run just re-attaches (see the mount effect above).
  async function pollRunAll() {
    setBulkRunning(true);
    try {
      for (;;) {
        const s = await api.pipeline.runAllStatus();
        setBulkLabel(
          s.in_flight.length
            ? `Running ${s.in_flight.join(', ')} (${s.done_count}/${s.total} done)…`
            : s.running
              ? 'Starting…'
              : 'Finishing…',
        );
        if (!s.running) {
          setBulkReport(
            s.done.map((o) => ({
              ticker: o.ticker,
              ok: o.ok,
              error: o.error ?? undefined,
              usageLimited: o.usage_limited,
            })),
          );
          break;
        }
        await new Promise((r) => setTimeout(r, 3000));
      }
    } finally {
      setBulkRunning(false);
      setBulkLabel(null);
      // Refresh scores/decisions now that the run has settled.
      await loadAll();
    }
  }

  // Kick off a server-side Run All over every covered stock, then poll its progress. A second click
  // (or another tab) is a no-op server-side — it just re-attaches to the running job.
  async function runAll() {
    if (bulkRunning || stocks.length === 0) return;
    setBulkReport(null);
    await api.pipeline.runAll();
    await pollRunAll();
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
        onAdd={() => setAddOpen(true)}
        onRunAll={runAll}
        bulkRunning={bulkRunning}
        bulkLabel={bulkLabel}
      />

      <AddStockModal open={addOpen} onClose={() => setAddOpen(false)} onSubmit={submitAdd} />

      {bulkReport && (() => {
        const failures = bulkReport.filter((r) => !r.ok);
        const okCount = bulkReport.length - failures.length;
        const failed = failures.length > 0;
        return (
          <div
            style={{
              background: failed ? 'var(--color-neg-bg)' : 'var(--color-surface)',
              border: '1px solid var(--color-rule)',
              color: failed ? 'var(--color-neg-fg)' : 'var(--color-ink-2)',
              padding: '10px 14px',
              borderRadius: 6,
              fontSize: 12.5,
              marginBottom: 16,
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: failed ? 6 : 0 }}>
              {failed
                ? `Pipeline run: ${okCount} succeeded, ${failures.length} failed`
                : `Pipeline run complete — all ${okCount} stocks refreshed`}
            </div>
            {failed && (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {failures.map((f) => (
                  <li key={f.ticker}>
                    <strong>{f.ticker}</strong>: {f.error ?? 'failed'}
                  </li>
                ))}
              </ul>
            )}
            <button
              onClick={() => setBulkReport(null)}
              style={{
                marginTop: failed ? 8 : 0,
                marginLeft: failed ? 0 : 8,
                textDecoration: 'underline',
                background: 'transparent',
                border: 'none',
                color: 'inherit',
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              Dismiss
            </button>
          </div>
        );
      })()}

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
