import { useNavigate } from 'react-router-dom';
import ChangePct from '../primitives/ChangePct';
import ScoreBar from '../primitives/ScoreBar';
import SignalBadge from '../primitives/SignalBadge';
import Sparkline, { genSparkSeed } from '../primitives/Sparkline';
import { fmtPrice } from '../primitives/format';
import type { WatchlistRow } from './rows';

interface Props {
  rows: WatchlistRow[];
}

function Th({ children, align = 'left', width }: { children: React.ReactNode; align?: 'left' | 'right' | 'center'; width?: string }) {
  return (
    <th
      style={{
        textAlign: align,
        padding: '10px 12px',
        fontSize: 10,
        letterSpacing: '.1em',
        textTransform: 'uppercase',
        color: 'var(--color-ink-3)',
        fontWeight: 600,
        width,
      }}
    >
      {children}
    </th>
  );
}

export default function WatchlistTable({ rows }: Props) {
  const navigate = useNavigate();
  return (
    <div
      style={{
        border: '1px solid var(--color-rule)',
        borderRadius: 8,
        overflow: 'hidden',
        background: 'var(--color-surface)',
      }}
    >
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-ui)' }}>
        <thead>
          <tr style={{ background: 'var(--color-surface-2)', borderBottom: '1px solid var(--color-rule)' }}>
            <Th width="80px">Ticker</Th>
            <Th>Name</Th>
            <Th align="right">Price</Th>
            <Th align="right">1D</Th>
            <Th width="90px">Trend (90D)</Th>
            <Th width="180px">Composite · screen</Th>
            <Th align="center" width="100px">
              Signal
            </Th>
            <Th align="right" width="60px">
              Flags
            </Th>
            <Th align="right" width="100px">
              Last run
            </Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s, i) => {
            const pad = '12px 12px';
            return (
              <tr
                key={s.ticker}
                onClick={() => navigate(`/stock/${s.ticker}`)}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLTableRowElement).style.background = 'var(--color-surface-2)')
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLTableRowElement).style.background = 'transparent')
                }
                style={{
                  borderBottom: i < rows.length - 1 ? '1px solid var(--color-rule-soft)' : 'none',
                  cursor: 'pointer',
                  transition: 'background .12s ease',
                }}
              >
                <td style={{ padding: pad, fontWeight: 600, color: 'var(--color-ink)', fontSize: 13 }}>{s.ticker}</td>
                <td style={{ padding: pad, maxWidth: 240 }}>
                  <div
                    style={{
                      color: 'var(--color-ink-2)',
                      fontSize: 12.5,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {s.name}
                  </div>
                  {s.archetype && (
                    <div
                      style={{
                        fontSize: 10,
                        color: 'var(--color-ink-3)',
                        letterSpacing: '.02em',
                        marginTop: 2,
                        textTransform: 'capitalize',
                      }}
                    >
                      {s.archetype.replace(/-/g, ' ')}
                    </div>
                  )}
                </td>
                <td
                  style={{
                    padding: pad,
                    textAlign: 'right',
                    fontFamily: 'var(--font-mono)',
                    fontVariantNumeric: 'tabular-nums',
                    fontSize: 12.5,
                    color: 'var(--color-ink)',
                  }}
                >
                  {fmtPrice(s.latest_price)}
                </td>
                <td style={{ padding: pad, textAlign: 'right', fontSize: 12.5 }}>
                  <ChangePct pct={s.price_change_pct} />
                </td>
                <td
                  style={{
                    padding: pad,
                    color:
                      (s.price_change_pct ?? 0) >= 0 ? 'var(--color-pos-fg)' : 'var(--color-neg-fg)',
                  }}
                >
                  <Sparkline data={genSparkSeed(s.ticker)} width={80} height={22} stroke="currentColor" />
                </td>
                <td style={{ padding: pad }}>
                  {s.composite_score != null ? (
                    <ScoreBar value={s.composite_score} height={5} showVal={true} />
                  ) : (
                    <span style={{ color: 'var(--color-ink-3)', fontSize: 11 }}>—</span>
                  )}
                </td>
                <td style={{ padding: pad, textAlign: 'center' }}>
                  {s.signal ? <SignalBadge signal={s.signal} size="xs" /> : <span style={{ color: 'var(--color-ink-3)' }}>—</span>}
                </td>
                <td
                  style={{
                    padding: pad,
                    textAlign: 'right',
                    fontFamily: 'var(--font-mono)',
                    fontVariantNumeric: 'tabular-nums',
                    fontSize: 12.5,
                    color: s.flag_count > 2 ? 'var(--color-warn-fg)' : 'var(--color-ink-2)',
                  }}
                >
                  {s.flag_count > 0 ? s.flag_count : '—'}
                </td>
                <td
                  style={{
                    padding: pad,
                    textAlign: 'right',
                    fontSize: 11.5,
                    color: 'var(--color-ink-3)',
                  }}
                >
                  {s.last_run ?? '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
