import { useState } from 'react';
import Card from '../primitives/Card';
import ConfidencePill from '../primitives/ConfidencePill';
import SignalBadge from '../primitives/SignalBadge';
import type { Decision } from '../../api/client';

type PtBasis = 'gaap' | 'operating';

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
          Decision · {decision.date}
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
      {decision.price_target && <PriceTargetBlock pt={decision.price_target} signal={decision.final_signal} />}
      {decision.position_sizing && <SizingBlock sizing={decision.position_sizing} />}
    </Card>
  );
}

const SCENARIO_ORDER = ['bear', 'base', 'bull'] as const;

function ScenarioLegsTable({
  scenarios,
  probabilities,
  basis,
}: {
  scenarios: NonNullable<NonNullable<Decision['price_target']>['scenarios']>;
  probabilities: Record<string, number | string>;
  basis: PtBasis;
}) {
  const cols = SCENARIO_ORDER.filter((s) => scenarios[s]);
  if (cols.length === 0) return null;
  const op = basis === 'operating';
  const dcfOf = (s: string) => (op ? scenarios[s]?.dcf_operating : scenarios[s]?.dcf);
  const multOf = (s: string) => (op ? scenarios[s]?.multiple_operating : scenarios[s]?.multiple);
  const blendOf = (s: string) => (op ? scenarios[s]?.blended_operating : scenarios[s]?.blended);
  const hasMultiple = !op && cols.some((s) => multOf(s) != null);
  const fmt = (v: number | null | undefined) => (v != null ? `$${v.toFixed(0)}` : '—');
  const cell: React.CSSProperties = {
    padding: '2px 10px 2px 0',
    fontFamily: 'var(--font-mono)',
    fontSize: 11.5,
    textAlign: 'right',
  };
  const label: React.CSSProperties = { ...cell, textAlign: 'left', color: 'var(--color-ink-3)' };
  return (
    <table style={{ borderCollapse: 'collapse', margin: '8px 0 0' }}>
      <thead>
        <tr>
          <th style={label} />
          {cols.map((s) => (
            <th key={s} style={{ ...cell, color: 'var(--color-ink-3)', fontWeight: 600, textTransform: 'capitalize' }}>
              {s}
              {typeof probabilities?.[s] === 'number' && (
                <span style={{ fontWeight: 400 }}> {((probabilities[s] as number) * 100).toFixed(0)}%</span>
              )}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {hasMultiple && <>
        <tr>
          <td style={label}>DCF at target date</td>
          {cols.map((s) => (
            <td key={s} style={cell}>{fmt(dcfOf(s))}</td>
          ))}
        </tr>
        <tr>
          <td style={label}>Forward-earnings value</td>
          {cols.map((s) => (
            <td key={s} style={cell}>{fmt(multOf(s))}</td>
          ))}
        </tr>
        </>}
        <tr>
          <td style={{ ...label, color: 'var(--color-ink-2)' }}>Scenario target</td>
          {cols.map((s) => (
            <td key={s} style={{ ...cell, fontWeight: 600, color: 'var(--color-ink)' }}>
              {fmt(blendOf(s))}
            </td>
          ))}
        </tr>
      </tbody>
    </table>
  );
}

function BasisToggle({ basis, onChange }: { basis: PtBasis; onChange: (b: PtBasis) => void }) {
  const opts: [PtBasis, string][] = [['gaap', 'GAAP'], ['operating', 'Operating DCF sensitivity']];
  return (
    <div style={{ display: 'inline-flex', marginTop: 6, border: '1px solid var(--color-rule)', borderRadius: 6, overflow: 'hidden', width: 'fit-content' }}>
      {opts.map(([key, lbl]) => {
        const active = basis === key;
        return (
          <button
            key={key}
            onClick={() => onChange(key)}
            title={key === 'operating'
              ? 'Sensitivity using an operating earnings-to-cash bridge; not company-reported non-GAAP EPS'
              : 'Value on reported GAAP net income'}
            style={{
              fontSize: 10, fontWeight: 500, padding: '3px 9px', border: 'none', cursor: 'pointer',
              background: active ? 'var(--color-ink)' : 'transparent',
              color: active ? 'var(--color-bg)' : 'var(--color-ink-3)',
            }}
          >
            {lbl}
          </button>
        );
      })}
    </div>
  );
}

function PriceTargetBlock({ pt, signal }: { pt: NonNullable<Decision['price_target']>; signal: string }) {
  const hasOperating = pt.modes?.operating?.price_target != null;
  const [selectedBasis, setBasis] = useState<PtBasis>('gaap');
  const basis = hasOperating ? selectedBasis : 'gaap';
  if (pt.price_target == null || pt.method?.status !== 'ready') return (
    <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--color-rule-soft)', fontSize: 12, lineHeight: 1.6 }}>
      <strong>{pt.method?.status === 'refresh_required' ? 'Valuation needs a refresh' : 'Valuation unavailable'}</strong>
      <p style={{ margin: '4px 0', color: 'var(--color-ink-2)' }}>{pt.method?.issues?.join(' ') || 'Run analysis to build dated scenarios with the current model.'}</p>
      <span style={{ color: 'var(--color-ink-3)' }}>Last calculation {pt.as_of} · forecast {pt.forecast_as_of || 'unavailable'}</span>
    </div>
  );
  const p = pt.probabilities || {};
  const probTxt = ['bull', 'base', 'bear']
    .map((k) => `${k} ${typeof p[k] === 'number' ? ((p[k] as number) * 100).toFixed(0) : '—'}%`)
    .join(' / ');
  // Selected basis drives the headline PT/upside; fall back to the scalar (GAAP) fields.
  const m = (hasOperating && pt.modes?.[basis]) || null;
  const shownPt = m?.price_target ?? pt.price_target;
  const shownUpside = m?.upside ?? pt.upside;
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
          {basis === 'operating' ? 'DCF target' : 'Target'} · {pt.method.target_date || `${pt.horizon_months}mo`}
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 22,
            fontWeight: 700,
            color:
              shownUpside != null
                ? shownUpside >= 0
                  ? 'var(--color-pos-fg)'
                  : 'var(--color-neg-fg)'
                : 'var(--color-ink)',
          }}
        >
          ${shownPt.toFixed(0)}
        </span>
        <span style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
          {shownUpside != null && (
            <>
              {shownUpside >= 0 ? '+' : ''}
              {(shownUpside * 100).toFixed(1)}% vs reference price
            </>
          )}
          {pt.street_target_mean != null && <>{' · street $'}{pt.street_target_mean.toFixed(0)} ({pt.method.street_as_of})</>}
        </span>
        <span style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
          Reference ${pt.price_at?.toFixed(2) ?? '—'} · {pt.method.price_date}
        </span>
        <span style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
          Present DCF ${(m?.fair_value ?? pt.fair_value)?.toFixed(0) ?? '—'} · {pt.as_of}
        </span>
        {hasOperating && <BasisToggle basis={basis} onChange={setBasis} />}
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
          P({probTxt}) · {pt.probabilities.source === 'judge' ? 'Judge weights' : 'Provisional weights'} · {basis === 'operating' ? 'DCF sensitivity' : pt.method?.w_dcf != null ? `Base method: ${(pt.method.w_dcf * 100).toFixed(0)}% DCF / ${(100 - pt.method.w_dcf * 100).toFixed(0)}% multiples` : ''}
          {basis === 'gaap' && pt.method.w_dcf !== 1 && pt.method?.multiple_basis ? ` · ${pt.method.multiple_basis}` : ''}
          {typeof pt.wacc?.cost_of_equity === 'number' ? ` · Cost of equity ${(pt.wacc.cost_of_equity * 100).toFixed(1)}%` : ''}
          {typeof pt.wacc?.beta === 'number' ? ` (β ${(pt.wacc.beta as number).toFixed(2)})` : ''}
        </p>
        {pt.scenarios && <ScenarioLegsTable scenarios={pt.scenarios} probabilities={pt.probabilities} basis={basis} />}
        {hasOperating && (
          <p style={{ fontSize: 10.5, color: 'var(--color-ink-3)', margin: '6px 0 0', fontStyle: 'italic' }}>
            {basis === 'operating'
              ? 'Operating DCF only, without the comparable-earnings blend. Uses a historical operating earnings-to-cash bridge and a 21% normalization tax; not company-reported non-GAAP EPS.'
              : 'GAAP earnings basis. Scenario targets value the cash flows and earnings remaining at the future target date.'}
          </p>
        )}
        <p style={{ fontSize: 11, color: 'var(--color-ink-3)', margin: '8px 0' }}>
          Forecast {pt.forecast_as_of}
          {basis === 'gaap' && Object.values(pt.scenarios || {}).some((s) => s.multiple != null) && <> · Multiple earnings window {pt.method.earnings_start} to {pt.method.earnings_end}</>}
        </p>
        {shownUpside != null && shownUpside < -.2 && ['BUY', 'STRONG_BUY'].includes(signal) && (
          <p style={{ fontSize: 12, color: 'var(--color-warn-fg)', margin: '8px 0' }}>
            Valuation and the buy thesis disagree. Review the growth, margin and multiple assumptions before adding capital; a lower price alone would not confirm the thesis.
          </p>
        )}
        {(pt.method.warnings || []).map((warning) => <p key={warning} style={{ fontSize: 11, color: 'var(--color-ink-2)' }}>{warning}</p>)}
        <details style={{ fontSize: 11, lineHeight: 1.6, color: 'var(--color-ink-2)', marginTop: 8 }}>
          <summary style={{ cursor: 'pointer' }}>Why this model and these assumptions</summary>
          <p>{pt.method.policy?.rationale}. {pt.method.policy?.source}.</p>
          <p>Scenario economics below compare revenue in the second forecast year with the first; margins cover that second year.</p>
          {SCENARIO_ORDER.map((name) => {
            const scenario = pt.scenarios?.[name];
            if (!scenario) return null;
            return <p key={name}>
              <strong style={{ textTransform: 'capitalize' }}>{name}</strong>
              {scenario.revenue_growth != null && <> · revenue growth {(scenario.revenue_growth * 100).toFixed(1)}%</>}
              {scenario.operating_margin != null && <> · operating margin {(scenario.operating_margin * 100).toFixed(1)}%</>}
              {basis === 'gaap' && scenario.w_dcf != null && <> · DCF weight {(scenario.w_dcf * 100).toFixed(0)}%</>}
            </p>;
          })}
          <p>{pt.method.comparable_anchor?.source}. {pt.method.comparable_anchor?.reason}</p>
          {Boolean(pt.method.comparable_anchor?.constituents?.length) && <p>Peers: {pt.method.comparable_anchor?.constituents?.map((c) => `${c.ticker} ${c.pe.toFixed(1)}× (weight ${c.weight.toFixed(2)})`).join(' · ')}</p>}
          <p>Cash conversion: {pt.method.cash_conversion?.observed_conversion?.toFixed(2) ?? '—'}× · {pt.method.cash_conversion?.source} · {pt.method.cash_conversion?.start} to {pt.method.cash_conversion?.end}.</p>
          {pt.method.share_funding && <p>
            Stock compensation: {(pt.method.share_funding.stock_comp_ratio * 100).toFixed(1)}% of revenue · {pt.method.share_funding.source} · {pt.method.share_funding.start} to {pt.method.share_funding.end}.
            {' '}Buybacks needed to reach the modeled share count reduce distributable cash flow, priced at a constant ${pt.method.share_funding.reference_price.toFixed(2)} per share. {pt.method.share_funding.assumption}
          </p>}
          <p>{pt.method.period_note} Growth-duration and multiple adjustments are declared assumptions, not calibrated forecasts. The DCF assumes zero net borrowing and uses historical cash conversion; financing and repurchase funding need review.</p>
        </details>
      </div>
    </div>
  );
}

function SizingBlock({ sizing }: { sizing: NonNullable<Decision['position_sizing']> }) {
  const actionLabel: Record<string, string> = {
    accumulate: 'Accumulate',
    hold: 'Hold — no new capital',
    trim: 'Trim',
    exit: 'Exit',
  };
  const delta = sizing.delta_pct ?? 0;
  const isAdd = delta > 0.25;
  const isTrim = delta < -0.25;
  // Headline = the action against the current holding: +add / −trim, else the target weight.
  const headline = isAdd
    ? `+${delta.toFixed(1)}%`
    : isTrim
      ? `−${Math.abs(delta).toFixed(1)}%`
      : `${sizing.target_weight_pct.toFixed(1)}%`;
  const headColor = isAdd ? 'var(--color-pos-fg)' : isTrim ? 'var(--color-neg-fg)' : 'var(--color-ink-3)';
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
          {isAdd ? 'Add' : isTrim ? 'Trim' : 'Position size'}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 700, color: headColor }}>
          {headline}
        </span>
        <span style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
          {actionLabel[sizing.action] ?? sizing.action}
          {' · target '}{sizing.target_weight_pct.toFixed(1)}%
          {' · now '}{(sizing.current_weight_pct ?? 0).toFixed(1)}%
          {' · cap '}{sizing.max_weight_pct.toFixed(0)}%
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
