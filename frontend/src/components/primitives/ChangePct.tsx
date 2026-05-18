import { fmtPct } from './format';

interface Props {
  pct: number | null | undefined;
}

export default function ChangePct({ pct }: Props) {
  if (pct == null) return <span style={{ color: 'var(--color-ink-3)' }}>—</span>;
  const color =
    pct > 0 ? 'var(--color-pos-fg)' : pct < 0 ? 'var(--color-neg-fg)' : 'var(--color-ink-2)';
  return (
    <span
      style={{
        color,
        fontFamily: 'var(--font-mono)',
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      {fmtPct(pct)}
    </span>
  );
}
