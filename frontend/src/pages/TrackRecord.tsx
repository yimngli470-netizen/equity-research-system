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
        Changed predictions are saved as separate revisions. Only explicitly registered events
        with eligible evidence receive new grades. Historical grades remain visible as legacy
        diagnostics; they are not validated probability scores.
      </p>

      {summary && <>
        <p style={{ color: 'var(--color-ink-2)' }}>{summary.note}</p>
        <SummaryStrip s={summary} pct={pct} num={num} />
        <p style={{ fontSize: 12, color: 'var(--color-ink-2)' }}>{summary.market_mark_note}</p>
      </>}

      {/* Event scores and preserved legacy diagnostics */}
      {calib && <CalibrationCard calib={calib} pct={pct} num={num} />}

      {/* Thesis ledger */}
      <Card padding={20} style={{ marginBottom: 18 }}>
        <SectionTitle>Thesis ledger</SectionTitle>
        <Table
          head={['Ticker', 'Date', 'Leaning', 'Conv.', 'Decision', 'Status', 'Legacy hit rate', 'Price return', 'vs SPY', 'Mark date']}
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
              <Td muted>{t.market_mark?.mark_date ?? 'frozen legacy'}</Td>
            </tr>
          ))}
        </Table>
        {theses.length === 0 && <Empty>No theses journaled yet.</Empty>}
      </Card>

      {/* Forecast accuracy */}
      <Card padding={20} style={{ marginBottom: 18 }}>
        <SectionTitle>Forecast ledger and legacy accuracy — our EPS vs street</SectionTitle>
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
}: {
  s: TrackRecordSummary;
  pct: (v: number | null | undefined, signed?: boolean) => string;
  num: (v: number | null | undefined, d?: number) => string;
}) {
  const cells: [string, string, string][] = [
    ['Theses', `${s.theses_graded} / ${s.theses_total}`, 'graded / total'],
    ['Marked excess return', pct(s.mean_marked_excess_return, true), `${s.theses_with_market_marks} price diagnostics`],
    ['Legacy hit rate', s.mean_hit_rate == null ? '—' : pct(s.mean_hit_rate), 'kill-criteria'],
    ['Forecasts', `${s.forecasts_graded} / ${s.forecasts_total}`, 'graded / total'],
    ['Legacy forecast MAPE', s.forecast_mape == null ? '—' : pct(s.forecast_mape), 'EPS error'],
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
  const o = calib.legacy_diagnostics?.overall ?? calib.overall;
  const events = calib.event_probabilities;
  return (
    <Card padding={20} style={{ marginBottom: 18 }}>
      <SectionTitle>Event probability scores</SectionTitle>
      <p style={{ fontSize: 12, color: 'var(--color-ink-2)' }}>{calib.note}</p>
      {events && events.n_primary_submissions > 0 ? (
        <Table head={['Forecaster', 'Registered', 'Scored', 'Brier', 'Log loss']}>
          {Object.entries(events.by_forecaster).map(([name, scores]) => (
            <tr key={name} style={rowStyle}>
              <Td>{name}</Td><Td mono>{scores.n_registered}</Td><Td mono>{scores.n_scored}</Td>
              <Td mono>{num(scores.brier, 3)}</Td>
              <Td mono>{scores.log_loss_infinite ? '∞' : num(scores.log_loss, 3)}</Td>
            </tr>
          ))}
        </Table>
      ) : <Empty>No registered event probabilities yet. Narrative conviction has no probability score.</Empty>}
      <SectionTitle>Legacy conviction diagnostics</SectionTitle>
      {o.n_graded === 0 ? (
        <Empty>
          No legacy graded theses. These historical comparisons do not establish probability calibration.
        </Empty>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 28, marginBottom: 14, fontSize: 12, color: 'var(--color-ink-2)' }}>
            <span>n = <b>{o.n_graded}</b></span>
            <span>Legacy squared error: <b style={{ fontFamily: 'var(--font-mono)' }}>{num(o.brier_directional, 3)}</b></span>
            <span>
              Conviction minus directional hit rate:{' '}
              <b style={{ fontFamily: 'var(--font-mono)', color: (o.overconfidence_gap ?? 0) > 0.05 ? 'var(--color-neg-fg)' : 'var(--color-ink)' }}>
                {pct(o.overconfidence_gap, true)}
              </b>
            </span>
          </div>
          <Table head={['Conviction bucket', 'n', 'Conviction (avg)', 'Direction hit rate', 'Difference']}>
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
                    {gap == null ? 'unavailable' : pct(gap, true)}
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
