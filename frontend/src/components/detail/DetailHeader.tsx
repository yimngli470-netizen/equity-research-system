import { Link } from 'react-router-dom';
import Btn from '../primitives/Btn';
import ChangePct from '../primitives/ChangePct';
import { fmtPrice, fmtCompactCurrency } from '../primitives/format';
import type { Stock, ValuationResponse } from '../../api/client';

interface Props {
  stock: Stock;
  valuation: ValuationResponse | null;
  onRunPipeline: () => void;
  onRemove: () => void;
  running: boolean;
}

function archetypeLabel(a: string): string {
  const s = a.replace(/-/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export default function DetailHeader({ stock, valuation, onRunPipeline, onRemove, running }: Props) {
  const meta: string[] = [];
  if (stock.sector) meta.push(stock.sector);
  if (stock.industry) meta.push(stock.industry);
  if (valuation?.market_cap != null) meta.push(`Mkt cap ${fmtCompactCurrency(valuation.market_cap)}`);
  if (valuation?.forward_pe != null) meta.push(`Fwd P/E ${valuation.forward_pe.toFixed(1)}`);
  if (valuation?.peg_ratio != null) meta.push(`PEG ${valuation.peg_ratio.toFixed(2)}`);

  return (
    <div style={{ marginBottom: 28 }}>
      <Link
        to="/"
        style={{
          fontSize: 12,
          color: 'var(--color-ink-2)',
          textDecoration: 'none',
          padding: '4px 0',
          display: 'inline-block',
          marginBottom: 14,
        }}
      >
        ← Coverage
      </Link>

      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 24,
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginBottom: 6, flexWrap: 'wrap' }}>
            <h1
              style={{
                fontSize: 36,
                fontWeight: 600,
                color: 'var(--color-ink)',
                margin: 0,
                letterSpacing: '-.02em',
              }}
            >
              {stock.ticker}
            </h1>
            <div style={{ fontSize: 16, color: 'var(--color-ink-2)' }}>{stock.name}</div>
            {stock.archetype && (
              <span
                title="Business-model archetype — sets the peer group and scoring weights"
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  letterSpacing: '.03em',
                  color: 'var(--color-ink-2)',
                  background: 'var(--color-surface-2)',
                  border: '1px solid var(--color-rule-soft)',
                  borderRadius: 4,
                  padding: '2px 8px',
                  whiteSpace: 'nowrap',
                }}
              >
                {archetypeLabel(stock.archetype)}
              </span>
            )}
          </div>
          {meta.length > 0 && (
            <div
              style={{
                display: 'flex',
                gap: 14,
                fontSize: 12,
                color: 'var(--color-ink-3)',
                flexWrap: 'wrap',
              }}
            >
              {meta.map((m, i) => (
                <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 14 }}>
                  {i > 0 && <span style={{ color: 'var(--color-ink-3)' }}>·</span>}
                  <span>{m}</span>
                </span>
              ))}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
          <div
            style={{
              fontSize: 32,
              fontWeight: 500,
              color: 'var(--color-ink)',
              fontFamily: 'var(--font-mono)',
              fontVariantNumeric: 'tabular-nums',
              letterSpacing: '-.02em',
            }}
          >
            {fmtPrice(stock.latest_price)}
          </div>
          <div style={{ fontSize: 13 }}>
            <ChangePct pct={stock.price_change_pct} />
            <span style={{ color: 'var(--color-ink-3)', marginLeft: 6 }}>today</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="danger" size="md" onClick={onRemove}>
              Remove
            </Btn>
            <Btn onClick={onRunPipeline} disabled={running} variant="primary" size="md">
              {running ? 'Running pipeline…' : 'Run full pipeline'}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}
