import Card from '../primitives/Card';
import type { ScreenRank } from '../../api/client';

interface Props {
  rank: ScreenRank;
}

function archetypeLabel(a: string | null): string {
  if (!a) return 'unclassified';
  const s = a.replace(/-/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export default function ScreenRankBar({ rank }: Props) {
  return (
    <Card padding={18} style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 20, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--color-ink-3)', fontWeight: 600 }}>
            Screen rank
          </div>
          <div style={{ fontSize: 22, fontWeight: 600, color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}>
            #{rank.rank}<span style={{ fontSize: 14, color: 'var(--color-ink-3)' }}> / {rank.total}</span>
            <span style={{ fontSize: 13, color: 'var(--color-ink-3)', fontWeight: 400, marginLeft: 10 }}>watchlist</span>
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--color-ink-3)', fontWeight: 600 }}>
            vs {archetypeLabel(rank.archetype)}
          </div>
          <div style={{ fontSize: 22, fontWeight: 600, color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}>
            #{rank.archetype_rank}<span style={{ fontSize: 14, color: 'var(--color-ink-3)' }}> / {rank.archetype_total}</span>
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 200, fontSize: 11, color: 'var(--color-ink-3)', lineHeight: 1.5 }}>
          Where this name sorts by composite among your watchlist and its archetype peers.
          A relative <strong>screen</strong> to surface candidates — not a buy/sell recommendation.
        </div>
      </div>
    </Card>
  );
}
