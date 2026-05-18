import Card from '../primitives/Card';
import ConfidencePill from '../primitives/ConfidencePill';
import SignalBadge from '../primitives/SignalBadge';
import type { Decision } from '../../api/client';

interface Props {
  decision: Decision;
}

export default function DecisionPanel({ decision }: Props) {
  return (
    <Card padding={24} style={{ marginBottom: 18 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 16,
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <SignalBadge signal={decision.final_signal} size="lg" variant="prominent" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <ConfidencePill confidence={decision.confidence} />
            <span style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
              Composite {decision.raw_composite.toFixed(2)} ·{' '}
              {decision.risk_flags.length} flag{decision.risk_flags.length !== 1 ? 's' : ''}
            </span>
          </div>
        </div>
        <div
          style={{
            fontSize: 11,
            color: 'var(--color-ink-3)',
            letterSpacing: '.06em',
            textTransform: 'uppercase',
            fontWeight: 600,
          }}
        >
          Decision
        </div>
      </div>
      <p
        style={{
          fontSize: 14,
          lineHeight: 1.65,
          color: 'var(--color-ink)',
          margin: 0,
          fontFamily: 'var(--font-ui)',
          textWrap: 'pretty' as const,
          maxWidth: '70ch',
        }}
      >
        {decision.reasoning}
      </p>
    </Card>
  );
}
