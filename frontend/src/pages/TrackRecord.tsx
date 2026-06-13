import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type {
  CalibrationReport,
  ForecastRow,
  ThesisRow,
  TrackRecordSummary,
} from '../api/client';
import Card from '../components/primitives/Card';

/** The Analyst Track Record (5.2): the accountability loop made visible — the thesis ledger with
 * benchmark-relative outcomes, forecast accuracy (ours vs street), and the conviction calibration
 * curve. Reads mostly "pending" early by design; fills in as kill-criteria dates pass and
 * forecast quarters file. */
export default function TrackRecord() {
  const [summary, setSummary] = useState<TrackRecordSummary | null>(null);
  const [theses, setTheses] = useState<ThesisRow[]>([]);
  const [forecasts, setForecasts] = useState<ForecastRow[]>([]);
  const [calib, setCalib] = useState<CalibrationReport | null>(null);

  useEffect(() => {
    api.trackRecord.summary().then(setSummary).catch(() => {});
    api.trackRecord.theses().then(setTheses).catch(() => setTheses([]));
    api.trackRecord.forecasts().then(setForecasts).catch(() => setForecasts([]));
    api.trackRecord.calibration().then(setCalib).catch(() => {});
  }, []);

  const pct = (v: number | null | undefined, signed = false) =>
    v == null ? '—' : `${signed && v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`;
  const num = (v: number | null | undefined, d = 2) => (v == null ? '—' : v.toFixed(d));

  return (
    <div>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--color-ink)', margin: '0 0 4px' }}>
        Analyst Track Record
      </h1>
      <p style={{ fontSize: 13, color: 'var(--color-ink-3)', margin: '0 0 24px', maxWidth: '70ch' }}>
        Every call is journaled, then graded against what happened — return vs the S&amp;P 500, the
        judge&apos;s falsifiable predictions, and our EPS forecasts vs the street. This is the only
        evidence that earns reliance, and it can&apos;t be backfilled.
      </p>

      {summary && <SummaryStrip s={summary} pct={pct} num={num} />}

      {/* Conviction calibration */}
      {calib && <CalibrationCard calib={calib} pct={pct} num={num} />}

      {/* Thesis ledger */}
      <Card padding={20} style={{ marginBottom: 18 }}>
        <SectionTitle>Thesis ledger</SectionTitle>
        <Table
          head={['Ticker', 'Date', 'Leaning', 'Conv.', 'Decision', 'Status', 'Hit rate', 'Return', 'vs SPY']}
        >
          {theses.map((t, i) => (
            <tr key={i} style={rowStyle}>
              <Td><Link to={`/stock/${t.ticker}`} style={linkStyle}>{t.ticker}</Link></Td>
              <Td muted>{t.as_of}</Td>
              <Td cap>{t.leaning ?? '—'}</Td>
              <Td mono>{num(t.conviction)}</Td>
              <Td>{t.decision_signal ?? '—'}</Td>
              <Td><StatusPill status={t.status} /></Td>
              <Td mono>{t.hit_rate == null ? '—' : pct(t.hit_rate)}</Td>
              <Td mono tone={t.realized_return}>{pct(t.realized_return, true)}</Td>
              <Td mono tone={t.excess_return}>{pct(t.excess_return, true)}</Td>
            </tr>
          ))}
        </Table>
        {theses.length === 0 && <Empty>No theses journaled yet.</Empty>}
      </Card>

      {/* Forecast accuracy */}
      <Card padding={20} style={{ marginBottom: 18 }}>
        <SectionTitle>Forecast accuracy — our EPS vs street</SectionTitle>
        <Table
          head={['Ticker', 'Date', 'Next-q (ours)', 'Street', 'Δ', 'NTM (ours)', 'Status', 'Resolved', 'MAPE', 'Beat street']}
        >
          {forecasts.map((f, i) => (
            <tr key={i} style={rowStyle}>
              <Td><Link to={`/stock/${f.ticker}`} style={linkStyle}>{f.ticker}</Link></Td>
              <Td muted>{f.as_of}</Td>
              <Td mono>{num(f.base_next_q_eps)}</Td>
              <Td mono>{num(f.street_next_q_eps)}</Td>
              <Td mono tone={f.eps_vs_street_next_q}>{pct(f.eps_vs_street_next_q, true)}</Td>
              <Td mono>{num(f.base_ntm_eps)}</Td>
              <Td><StatusPill status={f.status} /></Td>
              <Td mono>{f.n_quarters_resolved}</Td>
              <Td mono>{f.mape == null ? '—' : pct(f.mape)}</Td>
              <Td mono>{f.beat_street == null ? '—' : pct(f.beat_street)}</Td>
            </tr>
          ))}
        </Table>
        {forecasts.length === 0 && <Empty>No forecasts yet.</Empty>}
      </Card>
    </div>
  );
}

function SummaryStrip({
  s,
  pct,
  num,
}: {
  s: TrackRecordSummary;
  pct: (v: number | null | undefined, signed?: boolean) => string;
  num: (v: number | null | undefined, d?: number) => string;
}) {
  const cells: [string, string, string][] = [
    ['Theses', `${s.theses_graded} / ${s.theses_total}`, 'graded / total'],
    ['Mean excess return', pct(s.mean_excess_return, true), 'vs S&P 500'],
    ['Mean hit rate', s.mean_hit_rate == null ? '—' : pct(s.mean_hit_rate), 'kill-criteria'],
    ['Forecasts', `${s.forecasts_graded} / ${s.forecasts_total}`, 'graded / total'],
    ['Forecast MAPE', s.forecast_mape == null ? '—' : pct(s.forecast_mape), 'EPS error'],
  ];
  return (
    <Card padding={20} style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 28 }}>
        {cells.map(([label, value, sub]) => (
          <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: 10, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--color-ink-3)', fontWeight: 600 }}>
              {label}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 700, color: 'var(--color-ink)' }}>
              {value}
            </span>
            <span style={{ fontSize: 10, color: 'var(--color-ink-3)' }}>{sub}</span>
          </div>
        ))}
      </div>
      <p style={{ fontSize: 11, color: 'var(--color-ink-3)', margin: '14px 0 0', fontStyle: 'italic' }}>
        {s.note}
      </p>
    </Card>
  );
}

function CalibrationCard({
  calib,
  pct,
  num,
}: {
  calib: CalibrationReport;
  pct: (v: number | null | undefined, signed?: boolean) => string;
  num: (v: number | null | undefined, d?: number) => string;
}) {
  const o = calib.overall;
  return (
    <Card padding={20} style={{ marginBottom: 18 }}>
      <SectionTitle>Conviction calibration</SectionTitle>
      {o.n_graded === 0 ? (
        <Empty>
          No graded theses yet — calibration needs ~30–50 resolved calls to be meaningful (the
          one input that can&apos;t be bought; it accrues one graded thesis at a time).
        </Empty>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 28, marginBottom: 14, fontSize: 12, color: 'var(--color-ink-2)' }}>
            <span>n = <b>{o.n_graded}</b></span>
            <span>Brier (directional): <b style={{ fontFamily: 'var(--font-mono)' }}>{num(o.brier_directional, 3)}</b></span>
            <span>
              Over/under-confidence:{' '}
              <b style={{ fontFamily: 'var(--font-mono)', color: (o.overconfidence_gap ?? 0) > 0.05 ? 'var(--color-neg-fg)' : 'var(--color-ink)' }}>
                {pct(o.overconfidence_gap, true)}
              </b>
            </span>
          </div>
          <Table head={['Conviction bucket', 'n', 'Said (avg)', 'Actually right', 'Verdict']}>
            {o.buckets.filter((b) => b.n > 0).map((b, i) => {
              const said = b.mean_conviction ?? 0;
              const got = b.mean_directional;
              const gap = got == null ? null : said - got;
              return (
                <tr key={i} style={rowStyle}>
                  <Td mono>{(b.lo * 100).toFixed(0)}–{(b.hi * 100).toFixed(0)}%</Td>
                  <Td mono>{b.n}</Td>
                  <Td mono>{pct(b.mean_conviction)}</Td>
                  <Td mono>{got == null ? '—' : pct(got)}</Td>
                  <Td muted>
                    {gap == null ? 'pending' : Math.abs(gap) < 0.08 ? 'calibrated' : gap > 0 ? 'overconfident' : 'underconfident'}
                  </Td>
                </tr>
              );
            })}
          </Table>
        </>
      )}
    </Card>
  );
}

// ── small presentational helpers ────────────────────────────────────────────
const rowStyle: React.CSSProperties = { borderTop: '1px solid var(--color-rule-soft)' };
const linkStyle: React.CSSProperties = { color: 'var(--color-ink)', fontFamily: 'var(--font-mono)', textDecoration: 'none', fontWeight: 500 };

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--color-ink-3)', marginBottom: 12 }}>
      {children}
    </div>
  );
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
      <thead>
        <tr>
          {head.map((h) => (
            <th key={h} style={{ textAlign: 'left', padding: '0 12px 8px 0', color: 'var(--color-ink-3)', fontWeight: 600, fontSize: 11 }}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

function Td({
  children,
  mono,
  muted,
  cap,
  tone,
}: {
  children: React.ReactNode;
  mono?: boolean;
  muted?: boolean;
  cap?: boolean;
  tone?: number | null;
}) {
  const color =
    tone == null
      ? muted
        ? 'var(--color-ink-3)'
        : 'var(--color-ink)'
      : tone > 0
        ? 'var(--color-pos-fg)'
        : tone < 0
          ? 'var(--color-neg-fg)'
          : 'var(--color-ink)';
  return (
    <td
      style={{
        padding: '7px 12px 7px 0',
        color,
        fontFamily: mono ? 'var(--font-mono)' : undefined,
        textTransform: cap ? 'capitalize' : undefined,
      }}
    >
      {children}
    </td>
  );
}

function StatusPill({ status }: { status: string }) {
  const graded = status === 'graded';
  return (
    <span
      style={{
        fontSize: 10,
        padding: '1px 7px',
        borderRadius: 10,
        border: `1px solid ${graded ? 'var(--color-pos-fg)' : 'var(--color-rule)'}`,
        color: graded ? 'var(--color-pos-fg)' : 'var(--color-ink-3)',
        textTransform: 'uppercase',
        letterSpacing: '.04em',
      }}
    >
      {status}
    </span>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p style={{ fontSize: 12, color: 'var(--color-ink-3)', margin: '8px 0 0', maxWidth: '70ch' }}>{children}</p>;
}
