interface RowSummary {
  ticker: string;
  signal: string | null;
  flag_count: number;
  composite_score: number | null;
}

interface Props {
  rows: RowSummary[];
}

function Stat({ label, value, mono }: { label: string; value: string | number; mono?: boolean }) {
  return (
    <div style={{ textAlign: 'right' }}>
      <div
        style={{
          fontSize: 10,
          letterSpacing: '.12em',
          textTransform: 'uppercase',
          color: 'var(--color-ink-3)',
          fontWeight: 600,
          marginBottom: 2,
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 18,
          fontWeight: 500,
          color: 'var(--color-ink)',
          fontFamily: mono ? 'var(--font-mono)' : 'var(--font-ui)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </div>
    </div>
  );
}

export default function DashboardHeader({ rows }: Props) {
  const total = rows.length;
  const buys = rows.filter((s) => s.signal === 'BUY' || s.signal === 'STRONG_BUY').length;
  const flags = rows.reduce((acc, s) => acc + (s.flag_count ?? 0), 0);
  const scored = rows.filter((s) => s.composite_score != null);
  const avgScore = scored.length
    ? scored.reduce((acc, s) => acc + (s.composite_score ?? 0), 0) / scored.length
    : 0;

  const today = new Date().toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        gap: 24,
        marginBottom: 24,
      }}
    >
      <div>
        <div
          style={{
            fontSize: 11,
            letterSpacing: '.14em',
            textTransform: 'uppercase',
            color: 'var(--color-ink-3)',
            fontWeight: 600,
            marginBottom: 6,
          }}
        >
          Watchlist · {today}
        </div>
        <h1
          style={{
            fontSize: 30,
            fontWeight: 600,
            color: 'var(--color-ink)',
            margin: 0,
            letterSpacing: '-.02em',
          }}
        >
          Coverage
        </h1>
      </div>
      <div style={{ display: 'flex', gap: 28, alignItems: 'flex-end' }}>
        <Stat label="Tracked" value={total} />
        <Stat label="Buy signals" value={`${buys}/${total}`} />
        <Stat label="Open flags" value={flags} />
        <Stat label="Avg score" value={scored.length ? avgScore.toFixed(2) : '—'} mono />
      </div>
    </div>
  );
}
