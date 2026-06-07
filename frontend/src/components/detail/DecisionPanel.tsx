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
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <ConfidencePill confidence={decision.confidence} />
            <span style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
              {decision.raw_signal !== decision.final_signal ? (
                <>
                  Quant screen{' '}
                  <span style={{ textDecoration: 'line-through', color: 'var(--color-ink-3)' }}>
                    {decision.raw_signal.replace(/_/g, ' ')}
                  </span>{' '}
                  · adjusted ·{' '}
                </>
              ) : (
                <>Composite {decision.raw_composite.toFixed(2)} · </>
              )}
              {decision.risk_flags.length} flag{decision.risk_flags.length !== 1 ? 's' : ''}
            </span>
            {decision.judge_leaning && (
              <span style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
                Judge:{' '}
                <span style={{ color: 'var(--color-ink-2)', textTransform: 'capitalize' }}>
                  {decision.judge_leaning.replace(/_/g, ' ')}
                </span>
                {decision.judge_conviction != null && (
                  <>
                    {' · conviction '}
                    <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-2)' }}>
                      {decision.judge_conviction.toFixed(2)}
                    </span>
                  </>
                )}
              </span>
            )}
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
      {decision.position_sizing && <SizingBlock sizing={decision.position_sizing} />}
    </Card>
  );
}

function SizingBlock({ sizing }: { sizing: NonNullable<Decision['position_sizing']> }) {
  const accumulate = sizing.action === 'accumulate';
  const actionLabel: Record<string, string> = {
    accumulate: 'Accumulate',
    hold: 'Hold — no new capital',
    trim: 'Trim',
    exit: 'Exit',
  };
  return (
    <div
      style={{
        marginTop: 16,
        paddingTop: 16,
        borderTop: '1px solid var(--color-rule-soft)',
        display: 'flex',
        alignItems: 'flex-start',
        gap: 18,
        flexWrap: 'wrap',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 96 }}>
        <span
          style={{
            fontSize: 10,
            letterSpacing: '.06em',
            textTransform: 'uppercase',
            fontWeight: 600,
            color: 'var(--color-ink-3)',
          }}
        >
          Position size
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 22,
            fontWeight: 700,
            color: accumulate ? 'var(--color-ink)' : 'var(--color-ink-3)',
          }}
        >
          {accumulate ? `${sizing.target_weight_pct.toFixed(1)}%` : '—'}
        </span>
        <span style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
          {actionLabel[sizing.action] ?? sizing.action}
          {accumulate && (
            <>
              {' · '}
              <span style={{ textTransform: 'capitalize' }}>{sizing.tier}</span>
              {' · cap '}
              {sizing.max_weight_pct.toFixed(0)}%
            </>
          )}
        </span>
      </div>
      <p
        style={{
          flex: 1,
          minWidth: 200,
          fontSize: 12,
          lineHeight: 1.6,
          color: 'var(--color-ink-2)',
          margin: 0,
          fontFamily: 'var(--font-mono)',
          textWrap: 'pretty' as const,
        }}
      >
        {sizing.rationale}
      </p>
    </div>
  );
}
