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
      {decision.price_target && <PriceTargetBlock pt={decision.price_target} />}
      {decision.position_sizing && <SizingBlock sizing={decision.position_sizing} />}
    </Card>
  );
}

function PriceTargetBlock({ pt }: { pt: NonNullable<Decision['price_target']> }) {
  if (pt.price_target == null) return null;
  const p = pt.probabilities || {};
  const probTxt = ['bull', 'base', 'bear']
    .map((k) => `${k} ${typeof p[k] === 'number' ? ((p[k] as number) * 100).toFixed(0) : '—'}%`)
    .join(' / ');
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
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 110 }}>
        <span
          style={{
            fontSize: 10,
            letterSpacing: '.06em',
            textTransform: 'uppercase',
            fontWeight: 600,
            color: 'var(--color-ink-3)',
          }}
        >
          Price target · {pt.horizon_months}mo
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 22,
            fontWeight: 700,
            color:
              pt.upside != null
                ? pt.upside >= 0
                  ? 'var(--color-pos-fg)'
                  : 'var(--color-neg-fg)'
                : 'var(--color-ink)',
          }}
        >
          ${pt.price_target.toFixed(0)}
        </span>
        <span style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
          {pt.upside != null && (
            <>
              {pt.upside >= 0 ? '+' : ''}
              {(pt.upside * 100).toFixed(1)}% vs price
            </>
          )}
          {pt.street_target_mean != null && <>{' · street $'}{pt.street_target_mean.toFixed(0)}</>}
        </span>
      </div>
      <div style={{ flex: 1, minWidth: 220 }}>
        <p
          style={{
            fontSize: 12,
            lineHeight: 1.6,
            color: 'var(--color-ink-2)',
            margin: 0,
            fontFamily: 'var(--font-mono)',
            textWrap: 'pretty' as const,
          }}
        >
          P({probTxt}) · {pt.method?.w_dcf != null ? `${(pt.method.w_dcf * 100).toFixed(0)}% DCF / ${(100 - pt.method.w_dcf * 100).toFixed(0)}% multiples` : ''}
          {pt.method?.multiple_basis ? ` · ${pt.method.multiple_basis}` : ''}
          {typeof pt.wacc?.wacc === 'number' ? ` · WACC ${((pt.wacc.wacc as number) * 100).toFixed(1)}%` : ''}
          {typeof pt.wacc?.beta === 'number' ? ` (β ${(pt.wacc.beta as number).toFixed(2)})` : ''}
        </p>
        {pt.method?.forward_multiple_check && (
          <p
            style={{
              fontSize: 12,
              lineHeight: 1.6,
              color: 'var(--color-warn-fg, var(--color-ink-2))',
              margin: '6px 0 0',
              fontFamily: 'var(--font-mono)',
            }}
          >
            street-method check: ${pt.method.forward_multiple_check.value.toFixed(0)}
            {' '}(our NTM ${pt.method.forward_multiple_check.ntm_eps.toFixed(2)} × fwd P/E{' '}
            {pt.method.forward_multiple_check.fwd_pe.toFixed(1)}, no reversion) — the PT assumes
            mean reversion; this line shows our earnings on the street&apos;s method
          </p>
        )}
      </div>
    </div>
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
