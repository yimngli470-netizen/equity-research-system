import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { Book } from '../api/client';
import Card from '../components/primitives/Card';

/** Portfolio (roadmap 6.2) — the real book the sizing engine reasons about. Manual CRUD over
 * holdings + cash; the computed view shows weights of total capital, sector exposure, unrealized
 * P&L, portfolio beta vs SPY, and the holdings correlation matrix. This is what turns "target 5%"
 * into "you hold 3% → add 2%" on every decision. */
export default function Portfolio() {
  const [book, setBook] = useState<Book | null>(null);
  const [editing, setEditing] = useState(false);
  const [draftCash, setDraftCash] = useState('');
  const [form, setForm] = useState({ ticker: '', shares: '', cost_basis: '' });

  const load = useCallback(async () => {
    const b = await api.portfolio.book().catch(() => null);
    setBook(b);
    if (b) setDraftCash(String(b.cash));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function saveCash() {
    const v = parseFloat(draftCash);
    if (!Number.isNaN(v)) await api.portfolio.setCash(v);
    setEditing(false);
    await load();
  }

  async function addPosition() {
    const shares = parseFloat(form.shares);
    if (!form.ticker || Number.isNaN(shares)) return;
    await api.portfolio.upsertPosition(form.ticker.toUpperCase(), {
      shares,
      cost_basis: form.cost_basis ? parseFloat(form.cost_basis) : null,
    });
    setForm({ ticker: '', shares: '', cost_basis: '' });
    await load();
  }

  async function removePosition(ticker: string) {
    await api.portfolio.deletePosition(ticker);
    await load();
  }

  const usd = (v: number | null | undefined, d = 0) =>
    v == null ? '—' : `$${v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}`;
  const pct = (v: number | null | undefined, signed = false) =>
    v == null ? '—' : `${signed && v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`;

  const empty = book && book.n_positions === 0 && book.cash === 0;

  return (
    <div>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--color-ink)', margin: '0 0 4px' }}>Portfolio</h1>
      <p style={{ fontSize: 13, color: 'var(--color-ink-3)', margin: '0 0 22px', maxWidth: '74ch' }}>
        The real book the sizing engine reasons about. Weights are fractions of total capital
        (holdings + cash), so every decision reports the delta against what you actually hold — "add
        2%" or "trim 1.5%", not just an abstract target.
      </p>

      {book && (
        <Card padding={20} style={{ marginBottom: 18 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 30, alignItems: 'flex-end' }}>
            <Stat label="Total book" value={usd(book.total_book)} />
            <Stat label="Invested" value={usd(book.total_invested)} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Label>Cash ({pct(book.cash_pct)})</Label>
              {editing ? (
                <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <input value={draftCash} onChange={(e) => setDraftCash(e.target.value)} style={inputStyle(110)} />
                  <button onClick={saveCash} style={miniBtn(true)}>Save</button>
                </span>
              ) : (
                <span style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                  <Value>{usd(book.cash)}</Value>
                  <button onClick={() => setEditing(true)} style={linkBtn}>edit</button>
                </span>
              )}
            </div>
            <Stat label="Unrealized P&L" value={usd(book.total_unrealized_pnl)} tone={book.total_unrealized_pnl} />
            <Stat label="Portfolio β" value={book.portfolio_beta == null ? '—' : book.portfolio_beta.toFixed(2)} />
            <Stat label="Positions" value={String(book.n_positions)} />
          </div>
        </Card>
      )}

      {/* Holdings */}
      <Card padding={0} style={{ marginBottom: 18, overflow: 'hidden' }}>
        <SectionHead>Holdings</SectionHead>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr>
              {['Ticker', 'Sector', 'Shares', 'Cost', 'Last', 'Mkt value', 'Weight', 'P&L', 'β', ''].map((h, i) => (
                <th key={h + i} style={th(i)}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {book?.positions.map((p) => (
              <tr key={p.ticker} style={{ borderTop: '1px solid var(--color-rule-soft)' }}>
                <Td><Link to={`/stock/${p.ticker}`} style={tickLink}>{p.ticker}</Link></Td>
                <Td muted>{p.sector ?? '—'}</Td>
                <Td mono right>{p.shares}</Td>
                <Td mono right>{usd(p.cost_basis, 2)}</Td>
                <Td mono right>{usd(p.last_price, 2)}</Td>
                <Td mono right>{usd(p.market_value)}</Td>
                <Td mono right>{pct(p.weight)}</Td>
                <Td mono right tone={p.unrealized_pnl_pct}>{pct(p.unrealized_pnl_pct, true)}</Td>
                <Td mono right muted>{p.beta == null ? '—' : p.beta.toFixed(2)}</Td>
                <Td right><button onClick={() => removePosition(p.ticker)} style={linkBtn}>remove</button></Td>
              </tr>
            ))}
            {/* Add row */}
            <tr style={{ borderTop: '1px solid var(--color-rule)' }}>
              <Td><input placeholder="TICKER" value={form.ticker}
                onChange={(e) => setForm({ ...form, ticker: e.target.value })} style={inputStyle(72)} /></Td>
              <Td muted>—</Td>
              <Td right><input placeholder="shares" value={form.shares}
                onChange={(e) => setForm({ ...form, shares: e.target.value })} style={inputStyle(70)} /></Td>
              <Td right><input placeholder="cost" value={form.cost_basis}
                onChange={(e) => setForm({ ...form, cost_basis: e.target.value })} style={inputStyle(70)} /></Td>
              <Td colSpan={5} />
              <Td right><button onClick={addPosition} style={miniBtn(!!form.ticker && !!form.shares)}>Add</button></Td>
            </tr>
          </tbody>
        </table>
        {empty && (
          <p style={{ fontSize: 12, color: 'var(--color-ink-3)', padding: '14px 16px', margin: 0 }}>
            No holdings yet. Add positions + cash above; every stock's decision will then show the
            add/trim delta against your real weights.
          </p>
        )}
      </Card>

      {/* Sector + correlation */}
      {book && book.n_positions > 0 && (
        <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
          <Card padding={20} style={{ flex: '1 1 320px' }}>
            <SectionHead bare>Sector exposure</SectionHead>
            {Object.entries(book.sector_weights).map(([s, w]) => (
              <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '7px 0' }}>
                <span style={{ fontSize: 12, color: 'var(--color-ink-2)', width: 150 }}>{s}</span>
                <div style={{ flex: 1, height: 6, background: 'var(--color-rule)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(w * 100, 100)}%`, height: '100%', background: 'var(--color-ink-2)' }} />
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-ink)', width: 44, textAlign: 'right' }}>
                  {pct(w)}
                </span>
              </div>
            ))}
          </Card>
          <Card padding={20} style={{ flex: '1 1 320px' }}>
            <SectionHead bare>Most-correlated holdings</SectionHead>
            {book.top_correlations.length === 0 ? (
              <p style={{ fontSize: 12, color: 'var(--color-ink-3)', margin: 0 }}>Need ≥2 holdings with overlapping history.</p>
            ) : book.top_correlations.map((c, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, margin: '6px 0', color: 'var(--color-ink-2)' }}>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{c.a} · {c.b}</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: c.corr > 0.5 ? 'var(--color-neg-fg)' : 'var(--color-ink)' }}>
                  {c.corr.toFixed(2)}
                </span>
              </div>
            ))}
          </Card>
        </div>
      )}
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────
function Label({ children }: { children: React.ReactNode }) {
  return <span style={{ fontSize: 10, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--color-ink-3)', fontWeight: 600 }}>{children}</span>;
}
function Value({ children }: { children: React.ReactNode }) {
  return <span style={{ fontFamily: 'var(--font-mono)', fontSize: 19, fontWeight: 700, color: 'var(--color-ink)' }}>{children}</span>;
}
function Stat({ label, value, tone }: { label: string; value: string; tone?: number | null }) {
  const color = tone == null ? 'var(--color-ink)' : tone > 0 ? 'var(--color-pos-fg)' : tone < 0 ? 'var(--color-neg-fg)' : 'var(--color-ink)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Label>{label}</Label>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 19, fontWeight: 700, color }}>{value}</span>
    </div>
  );
}
function SectionHead({ children, bare }: { children: React.ReactNode; bare?: boolean }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase',
      color: 'var(--color-ink-3)', padding: bare ? '0 0 12px' : '14px 16px 10px',
    }}>{children}</div>
  );
}
const tickLink: React.CSSProperties = { color: 'var(--color-ink)', fontFamily: 'var(--font-mono)', textDecoration: 'none', fontWeight: 600 };
const linkBtn: React.CSSProperties = { fontSize: 11, color: 'var(--color-ink-3)', background: 'none', border: 'none', cursor: 'pointer', padding: 0, textDecoration: 'underline' };
function th(i: number): React.CSSProperties {
  return { textAlign: i >= 2 && i <= 8 ? 'right' : 'left', padding: '10px 12px', color: 'var(--color-ink-3)', fontWeight: 600, fontSize: 11, whiteSpace: 'nowrap' };
}
function Td({ children, mono, muted, right, tone, colSpan }: {
  children?: React.ReactNode; mono?: boolean; muted?: boolean; right?: boolean; tone?: number | null; colSpan?: number;
}) {
  const color = tone == null ? (muted ? 'var(--color-ink-3)' : 'var(--color-ink)') : tone > 0 ? 'var(--color-pos-fg)' : tone < 0 ? 'var(--color-neg-fg)' : 'var(--color-ink)';
  return (
    <td colSpan={colSpan} style={{ padding: '8px 12px', color, fontFamily: mono ? 'var(--font-mono)' : undefined, textAlign: right ? 'right' : 'left' }}>
      {children}
    </td>
  );
}
function inputStyle(w: number): React.CSSProperties {
  return { width: w, fontSize: 12, padding: '4px 7px', border: '1px solid var(--color-rule)', borderRadius: 5, background: 'var(--color-bg)', color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' };
}
function miniBtn(enabled: boolean): React.CSSProperties {
  return { fontSize: 11, fontWeight: 500, padding: '4px 12px', borderRadius: 6, border: '1px solid var(--color-ink)', background: enabled ? 'var(--color-ink)' : 'transparent', color: enabled ? 'var(--color-bg)' : 'var(--color-ink-3)', cursor: enabled ? 'pointer' : 'default' };
}
