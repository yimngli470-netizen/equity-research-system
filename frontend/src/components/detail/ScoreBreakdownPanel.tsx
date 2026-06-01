import Card from '../primitives/Card';
import ScoreBar from '../primitives/ScoreBar';
import type { StockScore } from '../../api/client';

// category score key -> (label, weight key in score.weights)
const CATEGORIES: { key: keyof StockScore; label: string; wkey: string }[] = [
  { key: 'growth_score', label: 'Growth', wkey: 'growth' },
  { key: 'valuation_score', label: 'Valuation', wkey: 'valuation' },
  { key: 'profitability_score', label: 'Profitability', wkey: 'profitability' },
  { key: 'event_score', label: 'Events', wkey: 'event' },
  { key: 'momentum_score', label: 'Momentum', wkey: 'momentum' },
  { key: 'sentiment_score', label: 'Sentiment', wkey: 'sentiment' },
  { key: 'risk_score', label: 'Risk', wkey: 'risk' },
];

// Fallback if the API didn't send per-archetype weights (older score rows).
const DEFAULT_WEIGHTS: Record<string, number> = {
  growth: 0.2, valuation: 0.2, profitability: 0.15, event: 0.15,
  momentum: 0.1, sentiment: 0.1, risk: 0.1,
};

interface Props {
  score: StockScore;
}

export default function ScoreBreakdownPanel({ score }: Props) {
  const weights = score.weights ?? DEFAULT_WEIGHTS;
  const archetypeWeighted = !!score.weights && !!score.archetype;

  return (
    <Card padding={24} style={{ marginBottom: 18 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 6,
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
          {archetypeWeighted ? `Weights: ${score.archetype}` : 'Weights: default'}
        </div>
      </div>
      <div style={{ fontSize: 11, color: 'var(--color-ink-3)', marginBottom: 16, lineHeight: 1.5 }}>
        A peer-relative <strong>screen rank</strong>, not a recommendation. Valuation is scored vs
        this name's peer group; category weights are set by its archetype.
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {CATEGORIES.map((c) => {
          const value = score[c.key] as number;
          const pct = Math.round((weights[c.wkey] ?? 0) * 100);
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
                {pct}%
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
