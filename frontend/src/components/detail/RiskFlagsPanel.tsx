import Card from '../primitives/Card';
import { flagTone } from '../primitives/tones';
import type { RiskFlag } from '../../api/client';

interface Props {
  flags: RiskFlag[];
}

export default function RiskFlagsPanel({ flags }: Props) {
  if (!flags || flags.length === 0) {
    return (
      <Card padding={20} style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 13, color: 'var(--color-pos-fg)' }}>
          No risk flags triggered — clean signal.
        </div>
      </Card>
    );
  }
  return (
    <Card padding={24} style={{ marginBottom: 18 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 14,
        }}
      >
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
          Risk flags
        </h3>
        <span style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>{flags.length} active</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {flags.map((f, i) => {
          const tone = flagTone(f.level);
          return (
            <div
              key={i}
              style={{
                display: 'grid',
                gridTemplateColumns: '70px 1fr auto',
                gap: 16,
                alignItems: 'center',
                padding: '10px 14px',
                borderLeft: `2px solid ${tone.dot}`,
                background: 'var(--color-surface-2)',
                borderRadius: 4,
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: '.08em',
                  textTransform: 'uppercase',
                  color: tone.fg,
                }}
              >
                {tone.label}
              </span>
              <div>
                <div style={{ fontSize: 13, color: 'var(--color-ink)', marginBottom: 2 }}>
                  {f.message}
                </div>
                <div
                  style={{
                    fontSize: 10.5,
                    color: 'var(--color-ink-3)',
                    letterSpacing: '.04em',
                  }}
                >
                  {f.rule} · {f.category}
                </div>
              </div>
              <span
                style={{
                  fontSize: 10,
                  color: 'var(--color-ink-3)',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                #{i + 1}
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
