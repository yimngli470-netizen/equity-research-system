import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { ScreenRow, UniverseStatus } from '../api/client';
import Card from '../components/primitives/Card';

/** Universe screen (roadmap 6.1) — the two-tier idea-generation surface. A ranked screen across the
 * ~520 S&P 500 + NASDAQ-100 names (tier-1: hard features + a provisional rule archetype, ~zero LLM),
 * with promote-to-watchlist as the explicit tier-2 transition into the full pull-model pipeline. */
const ARCHETYPES = [
  'cyclical-commodity', 'secular-grower', 'platform',
  'mature-compounder', 'financial', 'deep-value-turnaround',
];

export default function Universe() {
  const [rows, setRows] = useState<ScreenRow[]>([]);
  const [status, setStatus] = useState<UniverseStatus | null>(null);
  const [archetype, setArchetype] = useState<string | null>(null);
  const [tier, setTier] = useState<string | null>(null);
  const [promoting, setPromoting] = useState<Record<string, boolean>>({});
  const [showHow, setShowHow] = useState(false);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadScreen = useCallback(async () => {
    const data = await api.universe
      .screen({ archetype: archetype ?? undefined, tier: tier ?? undefined, limit: 600 })
      .catch(() => []);
    setRows(data);
    setLoading(false);
  }, [archetype, tier]);

  const loadStatus = useCallback(async () => {
    const s = await api.universe.status().catch(() => null);
    setStatus(s);
    return s;
  }, []);

  useEffect(() => { loadScreen(); }, [loadScreen]);
  useEffect(() => { loadStatus(); }, [loadStatus]);

  // While a refresh job (or any promotion) is running, poll status + re-pull the screen so counts
  // and new rows appear live; stop when everything settles.
  useEffect(() => {
    const anyRunning = status?.refresh_job.running
      || Object.values(status?.promotions ?? {}).some((p) => p.running);
    if (anyRunning && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        const s = await loadStatus();
        await loadScreen();
        const stillRunning = s?.refresh_job.running
          || Object.values(s?.promotions ?? {}).some((p) => p.running);
        if (!stillRunning && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      }, 4000);
    }
    return () => {
      if (pollRef.current && !anyRunning) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [status, loadStatus, loadScreen]);

  async function onRefresh() {
    await api.universe.refresh({ skip_fresh_days: 7 }).catch(() => {});
    await loadStatus();
  }

  async function onPromote(ticker: string) {
    setPromoting((p) => ({ ...p, [ticker]: true }));
    await api.universe.promote(ticker).catch(() => {});
    await loadStatus();
  }

  const refreshing = status?.refresh_job.running ?? false;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--color-ink)', margin: '0 0 4px' }}>
            Universe Screen
          </h1>
          <p style={{ fontSize: 13, color: 'var(--color-ink-3)', margin: '0 0 0', maxWidth: '74ch' }}>
            The S&amp;P 500 + NASDAQ-100, ranked by the peer-relative hard-feature screen — EDGAR
            financials, prices, and a provisional rule-based archetype, at ~zero LLM. Promote a name
            to run the full pipeline (agents, forecast, price target, journal) and add it to coverage.
            {' '}
            <button onClick={() => setShowHow((v) => !v)} style={howLinkStyle}>
              {showHow ? 'Hide scoring detail' : 'How is the composite scored?'}
            </button>
          </p>
        </div>
        <button onClick={onRefresh} disabled={refreshing} style={btnStyle(refreshing)}>
          {refreshing ? 'Refreshing…' : 'Refresh universe'}
        </button>
      </div>

      {showHow && <HowScored />}

      {status && <StatusStrip s={status} />}

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', margin: '4px 0 16px' }}>
        <Chip label="All archetypes" active={archetype === null} onClick={() => setArchetype(null)} />
        {ARCHETYPES.map((a) => (
          <Chip key={a} label={a} active={archetype === a} onClick={() => setArchetype(a)} />
        ))}
        <span style={{ width: 1, height: 18, background: 'var(--color-rule)', margin: '0 4px' }} />
        <Chip label="All tiers" active={tier === null} onClick={() => setTier(null)} />
        <Chip label="universe" active={tier === 'universe'} onClick={() => setTier('universe')} />
        <Chip label="watchlist" active={tier === 'watchlist'} onClick={() => setTier('watchlist')} />
      </div>

      <Card padding={0} style={{ overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr>
              {['#', 'Ticker', 'Name', 'Sector', 'Archetype', 'Arch. rank', 'Composite', 'Signal', ''].map((h, i) => (
                <th key={h + i} style={thStyle(i)}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.ticker} style={{ borderTop: '1px solid var(--color-rule-soft)' }}>
                <Td mono muted>{r.rank}</Td>
                <Td><Link to={`/stock/${r.ticker}`} style={linkStyle}>{r.ticker}</Link></Td>
                <Td muted ellipsis>{r.name}</Td>
                <Td muted>{r.sector ?? '—'}</Td>
                <Td>
                  <span style={{ textTransform: 'capitalize' }}>{r.archetype ?? '—'}</span>
                  {r.archetype_source === 'rules' && <ProvisionalBadge />}
                </Td>
                <Td mono muted>{r.archetype_rank}/{r.archetype_total}</Td>
                <Td mono><CompositeBar value={r.composite_score} /></Td>
                <Td><SignalPill signal={r.signal} /></Td>
                <Td>
                  {r.coverage_tier === 'universe' ? (
                    <button
                      onClick={() => onPromote(r.ticker)}
                      disabled={promoting[r.ticker] || status?.promotions[r.ticker]?.running}
                      style={promoteBtnStyle(promoting[r.ticker] || !!status?.promotions[r.ticker]?.running)}
                    >
                      {promoting[r.ticker] || status?.promotions[r.ticker]?.running ? 'Promoting…' : 'Promote'}
                    </button>
                  ) : (
                    <span style={{ fontSize: 10, color: 'var(--color-pos-fg)', textTransform: 'uppercase', letterSpacing: '.04em' }}>
                      covered
                    </span>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && rows.length === 0 && (
          <p style={{ fontSize: 12, color: 'var(--color-ink-3)', padding: 20, margin: 0 }}>
            No scored names yet. Click <b>Refresh universe</b> to batch-ingest the S&amp;P 500 +
            NASDAQ-100 (tier-1, ~zero LLM). The list fills in as names are scored.
          </p>
        )}
      </Card>
    </div>
  );
}

function HowScored() {
  const rows: [string, string, string][] = [
    ['Growth', '~30%', 'Revenue & EPS YoY, consistency, acceleration — from EDGAR financials.'],
    ['Profitability', '~23%', 'Operating/net margins, margin trend, FCF conversion.'],
    ['Valuation', '~31%', 'PEER-RELATIVE: each multiple (P/E, P/S, FCF yield) becomes its percentile within the archetype peer set — not a fixed absolute ruler. With ~520 names the peer pools are real.'],
    ['Momentum', '~15%', '1 / 3 / 12-month price returns.'],
  ];
  return (
    <Card padding={20} style={{ margin: '4px 0 18px', background: 'var(--color-surface-2)' }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--color-ink-3)', marginBottom: 10 }}>
        How the tier-1 composite is scored
      </div>
      <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--color-ink-2)', margin: '0 0 12px', maxWidth: '78ch' }}>
        Universe names run through the <b>same scoring engine as the watchlist, minus the AI layer</b>.
        Four hard-fundamental categories are each scored, then combined with{' '}
        <b>archetype-conditioned weights</b> (a cyclical and a compounder aren&apos;t judged on the same
        ruler) into the 0–1 composite. No LLM is involved — this is the deterministic screen the backtest
        validated (rank-IC +0.017, top-vs-bottom decile spread ~+4%/yr).
      </p>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
        <tbody>
          {rows.map(([cat, w, desc]) => (
            <tr key={cat} style={{ borderTop: '1px solid var(--color-rule-soft)' }}>
              <td style={{ padding: '7px 12px 7px 0', fontWeight: 600, color: 'var(--color-ink)', whiteSpace: 'nowrap', verticalAlign: 'top' }}>{cat}</td>
              <td style={{ padding: '7px 12px 7px 0', fontFamily: 'var(--font-mono)', color: 'var(--color-ink-3)', verticalAlign: 'top' }}>{w}</td>
              <td style={{ padding: '7px 0', color: 'var(--color-ink-2)', lineHeight: 1.5 }}>{desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ fontSize: 11.5, color: 'var(--color-ink-3)', margin: '12px 0 0', fontStyle: 'italic', maxWidth: '78ch' }}>
        The AI categories (sentiment / risk / event) have no agent coverage for universe names, so they
        sit at neutral — <b>promote</b> a name to add the full agent dialectic, forecast, and price
        target. Weights shown are the secular-grower profile and shift by archetype.
      </p>
    </Card>
  );
}

function StatusStrip({ s }: { s: UniverseStatus }) {
  const job = s.refresh_job;
  const cells: [string, string][] = [
    ['Universe', String(s.universe)],
    ['Watchlist', String(s.watchlist)],
    ['Scored', String(s.scored)],
    ['Constituents', s.constituents_as_of ?? '—'],
  ];
  return (
    <Card padding={16} style={{ margin: '16px 0' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 28, alignItems: 'center' }}>
        {cells.map(([label, value]) => (
          <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <span style={{ fontSize: 10, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--color-ink-3)', fontWeight: 600 }}>
              {label}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: 'var(--color-ink)' }}>
              {value}
            </span>
          </div>
        ))}
        {job.running && (
          <span style={{ fontSize: 11, color: 'var(--color-ink-2)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <Spinner /> Tier-1 ingest running…
          </span>
        )}
        {!job.running && job.summary && (
          <span style={{ fontSize: 11, color: 'var(--color-ink-3)', fontStyle: 'italic' }}>
            Last refresh: {Object.entries(job.summary).map(([k, v]) => `${k} ${v}`).join(' · ')}
            {job.error_count ? ` · ${job.error_count} with errors` : ''}
          </span>
        )}
      </div>
    </Card>
  );
}

// ── presentational helpers ───────────────────────────────────────────────────
const linkStyle: React.CSSProperties = { color: 'var(--color-ink)', fontFamily: 'var(--font-mono)', textDecoration: 'none', fontWeight: 600 };
const howLinkStyle: React.CSSProperties = { background: 'none', border: 'none', padding: 0, color: 'var(--color-ink-2)', textDecoration: 'underline', cursor: 'pointer', fontSize: 13 };

function thStyle(i: number): React.CSSProperties {
  return { textAlign: i >= 5 && i <= 6 ? 'right' : 'left', padding: '12px 12px 10px', color: 'var(--color-ink-3)', fontWeight: 600, fontSize: 11, whiteSpace: 'nowrap' };
}

function Td({ children, mono, muted, ellipsis }: {
  children: React.ReactNode; mono?: boolean; muted?: boolean; ellipsis?: boolean;
}) {
  return (
    <td style={{
      padding: '8px 12px',
      color: muted ? 'var(--color-ink-3)' : 'var(--color-ink)',
      fontFamily: mono ? 'var(--font-mono)' : undefined,
      maxWidth: ellipsis ? 200 : undefined,
      overflow: ellipsis ? 'hidden' : undefined,
      textOverflow: ellipsis ? 'ellipsis' : undefined,
      whiteSpace: ellipsis ? 'nowrap' : undefined,
    }}>
      {children}
    </td>
  );
}

function CompositeBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8 }}>
      <span style={{ fontVariantNumeric: 'tabular-nums' }}>{value.toFixed(3)}</span>
      <div style={{ width: 54, height: 5, background: 'var(--color-rule)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: 'var(--color-ink-2)' }} />
      </div>
    </div>
  );
}

function SignalPill({ signal }: { signal: string }) {
  const pos = signal === 'BUY' || signal === 'STRONG_BUY';
  const neg = signal === 'SELL' || signal === 'REDUCE';
  const color = pos ? 'var(--color-pos-fg)' : neg ? 'var(--color-neg-fg)' : 'var(--color-ink-2)';
  return (
    <span style={{ fontSize: 10, padding: '1px 7px', borderRadius: 10, border: `1px solid ${color}`, color, textTransform: 'uppercase', letterSpacing: '.04em', whiteSpace: 'nowrap' }}>
      {signal.replace('_', ' ')}
    </span>
  );
}

function ProvisionalBadge() {
  return (
    <span title="Provisional rule-based label — upgraded to a grounded-LLM label on promotion"
      style={{ marginLeft: 6, fontSize: 9, padding: '0 5px', borderRadius: 8, border: '1px dashed var(--color-rule)', color: 'var(--color-ink-3)', textTransform: 'uppercase', letterSpacing: '.04em', verticalAlign: 'middle' }}>
      prov
    </span>
  );
}

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      fontSize: 11, padding: '4px 10px', borderRadius: 14,
      border: `1px solid ${active ? 'var(--color-ink)' : 'var(--color-rule)'}`,
      background: active ? 'var(--color-ink)' : 'transparent',
      color: active ? 'var(--color-bg)' : 'var(--color-ink-2)',
      cursor: 'pointer', textTransform: 'capitalize', transition: 'all .12s ease',
    }}>
      {label}
    </button>
  );
}

function btnStyle(disabled: boolean): React.CSSProperties {
  return {
    fontSize: 12, fontWeight: 500, padding: '8px 16px', borderRadius: 7, whiteSpace: 'nowrap',
    border: '1px solid var(--color-ink)', background: disabled ? 'transparent' : 'var(--color-ink)',
    color: disabled ? 'var(--color-ink-3)' : 'var(--color-bg)',
    cursor: disabled ? 'default' : 'pointer',
  };
}

function promoteBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    fontSize: 11, fontWeight: 500, padding: '3px 11px', borderRadius: 6, whiteSpace: 'nowrap',
    border: `1px solid ${disabled ? 'var(--color-rule)' : 'var(--color-ink-3)'}`,
    background: 'transparent', color: disabled ? 'var(--color-ink-3)' : 'var(--color-ink)',
    cursor: disabled ? 'default' : 'pointer',
  };
}

function Spinner() {
  return (
    <span style={{
      display: 'inline-block', width: 11, height: 11, borderRadius: '50%',
      border: '2px solid var(--color-rule)', borderTopColor: 'var(--color-ink-2)',
      animation: 'spin 0.8s linear infinite',
    }} />
  );
}
