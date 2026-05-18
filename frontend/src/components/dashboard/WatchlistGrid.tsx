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

function GridCard({ s }: { s: WatchlistRow }) {
  const navigate = useNavigate();
  return (
    <div
      onClick={() => navigate(`/stock/${s.ticker}`)}
      onMouseEnter={(e) =>
        ((e.currentTarget as HTMLDivElement).style.borderColor = 'var(--color-ink-3)')
      }
      onMouseLeave={(e) =>
        ((e.currentTarget as HTMLDivElement).style.borderColor = 'var(--color-rule)')
      }
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-rule)',
        borderRadius: 8,
        padding: 18,
        cursor: 'pointer',
        transition: 'border-color .12s ease',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: 14,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: 'var(--color-ink)',
              letterSpacing: '-.01em',
            }}
          >
            {s.ticker}
          </div>
          <div
            style={{
              fontSize: 11.5,
              color: 'var(--color-ink-3)',
              marginTop: 1,
              maxWidth: 180,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {s.name}
          </div>
        </div>
        {s.signal && <SignalBadge signal={s.signal} size="xs" />}
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          marginBottom: 12,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 22,
              fontWeight: 500,
              color: 'var(--color-ink)',
              fontFamily: 'var(--font-mono)',
              fontVariantNumeric: 'tabular-nums',
              letterSpacing: '-.02em',
            }}
          >
            {fmtPrice(s.latest_price)}
          </div>
          <div style={{ fontSize: 12, marginTop: 2 }}>
            <ChangePct pct={s.price_change_pct} />
          </div>
        </div>
        <div
          style={{
            color:
              (s.price_change_pct ?? 0) >= 0 ? 'var(--color-pos-fg)' : 'var(--color-neg-fg)',
          }}
        >
          <Sparkline data={genSparkSeed(s.ticker)} width={72} height={28} stroke="currentColor" />
        </div>
      </div>

      <div
        style={{
          borderTop: '1px solid var(--color-rule-soft)',
          paddingTop: 12,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span
              style={{
                fontSize: 10,
                letterSpacing: '.1em',
                textTransform: 'uppercase',
                color: 'var(--color-ink-3)',
                fontWeight: 600,
              }}
            >
              Composite
            </span>
            <span
              style={{
                fontSize: 12,
                fontFamily: 'var(--font-mono)',
                fontVariantNumeric: 'tabular-nums',
                color: 'var(--color-ink)',
              }}
            >
              {s.composite_score != null ? s.composite_score.toFixed(2) : '—'}
            </span>
          </div>
          {s.composite_score != null ? (
            <ScoreBar value={s.composite_score} height={4} showVal={false} />
          ) : (
            <div
              style={{
                height: 4,
                background: 'var(--color-rule-soft)',
                borderRadius: 2,
              }}
            />
          )}
        </div>
        {s.flag_count > 0 && (
          <div
            title={`${s.flag_count} risk flag${s.flag_count > 1 ? 's' : ''}`}
            style={{
              fontSize: 10,
              color: s.flag_count > 2 ? 'var(--color-warn-fg)' : 'var(--color-ink-3)',
              fontWeight: 600,
              fontFamily: 'var(--font-mono)',
            }}
          >
            {s.flag_count}⚑
          </div>
        )}
      </div>
    </div>
  );
}

export default function WatchlistGrid({ rows }: Props) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
        gap: 12,
      }}
    >
      {rows.map((s) => (
        <GridCard key={s.ticker} s={s} />
      ))}
    </div>
  );
}
