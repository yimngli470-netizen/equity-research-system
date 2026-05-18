import { useEffect, useState } from 'react';
import Card from '../primitives/Card';

interface Financial {
  ticker: string;
  period: string;
  period_end_date: string;
  revenue: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  net_income: number | null;
  eps: number | null;
}

function fmtM(v: number | null): string {
  if (v == null) return '—';
  return (v / 1e6).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function Th({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <th
      style={{
        textAlign: align,
        padding: '12px 16px',
        fontSize: 10,
        letterSpacing: '.1em',
        textTransform: 'uppercase',
        color: 'var(--color-ink-3)',
        fontWeight: 600,
        fontFamily: 'var(--font-ui)',
      }}
    >
      {children}
    </th>
  );
}

export default function FinancialsTable({ ticker, refreshKey = 0 }: { ticker: string; refreshKey?: number }) {
  const [rows, setRows] = useState<Financial[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/stocks/${ticker}/financials?limit=8`)
      .then((r) => r.json())
      .then((data) => setRows(data))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [ticker, refreshKey]);

  if (loading) {
    return (
      <Card padding={20}>
        <div style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>Loading financials…</div>
      </Card>
    );
  }
  if (rows.length === 0) {
    return (
      <Card padding={20}>
        <div style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>No financial data available.</div>
      </Card>
    );
  }

  return (
    <Card padding={0}>
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--color-rule)' }}>
        <h3
          style={{
            fontSize: 13,
            letterSpacing: '.1em',
            textTransform: 'uppercase',
            color: 'var(--color-ink-3)',
            fontWeight: 600,
            margin: 0,
          }}
        >
          Quarterly financials
        </h3>
      </div>
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontFamily: 'var(--font-mono)',
        }}
      >
        <thead>
          <tr>
            <Th>Period</Th>
            <Th align="right">Revenue ($M)</Th>
            <Th align="right">Gross</Th>
            <Th align="right">Operating</Th>
            <Th align="right">Net</Th>
            <Th align="right">EPS</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.period_end_date} style={{ borderTop: '1px solid var(--color-rule-soft)' }}>
              <td
                style={{
                  padding: '10px 16px',
                  fontSize: 12.5,
                  color: 'var(--color-ink)',
                  fontFamily: 'var(--font-ui)',
                }}
              >
                {r.period}
              </td>
              <td
                style={{
                  padding: '10px 16px',
                  textAlign: 'right',
                  fontSize: 12.5,
                  fontVariantNumeric: 'tabular-nums',
                  color: 'var(--color-ink)',
                }}
              >
                {fmtM(r.revenue)}
              </td>
              <td
                style={{
                  padding: '10px 16px',
                  textAlign: 'right',
                  fontSize: 12.5,
                  fontVariantNumeric: 'tabular-nums',
                  color: 'var(--color-ink-2)',
                }}
              >
                {fmtM(r.gross_profit)}
              </td>
              <td
                style={{
                  padding: '10px 16px',
                  textAlign: 'right',
                  fontSize: 12.5,
                  fontVariantNumeric: 'tabular-nums',
                  color: 'var(--color-ink-2)',
                }}
              >
                {fmtM(r.operating_income)}
              </td>
              <td
                style={{
                  padding: '10px 16px',
                  textAlign: 'right',
                  fontSize: 12.5,
                  fontVariantNumeric: 'tabular-nums',
                  color: 'var(--color-ink-2)',
                }}
              >
                {fmtM(r.net_income)}
              </td>
              <td
                style={{
                  padding: '10px 16px',
                  textAlign: 'right',
                  fontSize: 12.5,
                  fontVariantNumeric: 'tabular-nums',
                  color: 'var(--color-ink)',
                }}
              >
                {r.eps != null ? r.eps.toFixed(2) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
