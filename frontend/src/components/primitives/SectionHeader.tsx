import type { ReactNode } from 'react';

interface Props {
  kicker?: string;
  title: string;
  sub?: string;
  actions?: ReactNode;
}

export default function SectionHeader({ kicker, title, sub, actions }: Props) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, marginBottom: 14 }}>
      <div>
        {kicker && (
          <div
            style={{
              fontSize: 10,
              letterSpacing: '.12em',
              textTransform: 'uppercase',
              color: 'var(--color-ink-3)',
              fontWeight: 600,
              marginBottom: 4,
            }}
          >
            {kicker}
          </div>
        )}
        <h2 style={{ fontSize: 18, fontWeight: 600, color: 'var(--color-ink)', margin: 0, letterSpacing: '-.01em' }}>
          {title}
        </h2>
        {sub && <div style={{ fontSize: 12, color: 'var(--color-ink-2)', marginTop: 4 }}>{sub}</div>}
      </div>
      {actions && <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>{actions}</div>}
    </div>
  );
}
