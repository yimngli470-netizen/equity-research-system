import Card from '../primitives/Card';
import ScoreBar from '../primitives/ScoreBar';
import type { StockScore } from '../../api/client';

const CATEGORIES: { key: keyof StockScore; label: string; weight: number }[] = [
  { key: 'growth_score', label: 'Growth', weight: 20 },
  { key: 'valuation_score', label: 'Valuation', weight: 20 },
  { key: 'profitability_score', label: 'Profitability', weight: 15 },
  { key: 'event_score', label: 'Events', weight: 15 },
  { key: 'momentum_score', label: 'Momentum', weight: 10 },
  { key: 'sentiment_score', label: 'Sentiment', weight: 10 },
  { key: 'risk_score', label: 'Risk', weight: 10 },
];

interface Props {
  score: StockScore;
}

export default function ScoreBreakdownPanel({ score }: Props) {
  return (
    <Card padding={24} style={{ marginBottom: 18 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 18,
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
          Score breakdown
        </h3>
        <div style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
          Composite = Σ weight × category
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {CATEGORIES.map((c) => {
          const value = score[c.key] as number;
          return (
            <div
              key={c.key}
              style={{
                display: 'grid',
                gridTemplateColumns: '110px 36px 1fr 40px',
                gap: 12,
                alignItems: 'center',
              }}
            >
              <span style={{ fontSize: 13, color: 'var(--color-ink)' }}>{c.label}</span>
              <span
                style={{
                  fontSize: 10,
                  color: 'var(--color-ink-3)',
                  fontFamily: 'var(--font-mono)',
                  textAlign: 'right',
                }}
              >
                {c.weight}%
              </span>
              <div style={{ minWidth: 0 }}>
                <ScoreBar value={value} height={6} showVal={false} />
              </div>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontVariantNumeric: 'tabular-nums',
                  fontSize: 12,
                  color: 'var(--color-ink)',
                  textAlign: 'right',
                }}
              >
                {value.toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
