import type { NormalizedAgent, TileTone } from './agentView';

const TONE_COLOR: Record<TileTone, string> = {
  pos: 'var(--color-pos-fg)',
  neg: 'var(--color-neg-fg)',
  warn: 'var(--color-warn-fg)',
  muted: 'var(--color-ink-3)',
};

function Stat({ label, value, tone }: { label: string; value: string; tone?: TileTone }) {
  return (
    <div style={{ padding: 12, background: 'var(--color-surface-2)', borderRadius: 6 }}>
      <div
        style={{
          fontSize: 10,
          letterSpacing: '.08em',
          textTransform: 'uppercase',
          color: 'var(--color-ink-3)',
          fontWeight: 600,
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 16,
          fontFamily: 'var(--font-mono)',
          fontVariantNumeric: 'tabular-nums',
          color: tone ? TONE_COLOR[tone] : 'var(--color-ink)',
          fontStyle: tone === 'muted' ? 'italic' : undefined,
          textTransform: tone || /[a-z]/.test(value[0] || '') ? undefined : 'none',
        }}
      >
        {value}
      </div>
    </div>
  );
}

function EvidenceNote({ note }: { note: NonNullable<NormalizedAgent['evidence_note']> }) {
  if (!note) return null;
  const sourceLabel: Record<string, string> = {
    transcript: 'earnings call transcript',
    management_guidance: 'management guidance',
    analyst_consensus: 'analyst consensus estimates',
    financial_trend_only: 'historical financials only — no transcript or guidance available',
    unavailable: 'no forward-looking sources available',
  };
  const label = (note.evidence_source && sourceLabel[note.evidence_source]) || note.evidence_source || 'unavailable';
  return (
    <div
      style={{
        marginBottom: 12,
        padding: '10px 12px',
        borderLeft: '2px solid var(--color-watch-fg)',
        background: 'var(--color-watch-bg)',
        borderRadius: 4,
        fontSize: 12.5,
        color: 'var(--color-ink-2)',
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'baseline' }}>
        <span style={{ color: 'var(--color-watch-fg)', fontWeight: 600, fontSize: 10, letterSpacing: '.08em', textTransform: 'uppercase' }}>
          Forward outlook
        </span>
        <span>Source: {label}</span>
      </div>
      {note.missing_data.length > 0 && (
        <div style={{ marginTop: 4, color: 'var(--color-ink-3)', fontSize: 11.5 }}>
          Missing: {note.missing_data.join(', ')}
        </div>
      )}
    </div>
  );
}

interface Props {
  agent: NormalizedAgent;
}

export default function AgentBody({ agent }: Props) {
  return (
    <div>
      {agent.summary && (
        <p
          style={{
            fontSize: 13.5,
            lineHeight: 1.65,
            color: 'var(--color-ink)',
            margin: '0 0 14px',
            textWrap: 'pretty' as const,
            maxWidth: '68ch',
          }}
        >
          {agent.summary}
        </p>
      )}

      {agent.agent_type === 'news' && agent.news_items && agent.news_items.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {agent.news_items.map((h, i) => (
            <div
              key={i}
              style={{
                display: 'grid',
                gridTemplateColumns: '60px 1fr 70px 50px',
                gap: 12,
                alignItems: 'center',
                fontSize: 12.5,
                padding: '6px 0',
                borderTop: i ? '1px solid var(--color-rule-soft)' : 'none',
              }}
            >
              <span
                style={{
                  color: 'var(--color-ink-3)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                }}
              >
                {h.date}
              </span>
              <span style={{ color: 'var(--color-ink)' }}>{h.headline}</span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontVariantNumeric: 'tabular-nums',
                  color: h.tone === 'neg' ? 'var(--color-neg-fg)' : 'var(--color-pos-fg)',
                  textAlign: 'right',
                }}
              >
                {h.impact}
              </span>
              <span
                style={{
                  fontSize: 10,
                  color: 'var(--color-ink-3)',
                  textTransform: 'uppercase',
                  letterSpacing: '.06em',
                  textAlign: 'right',
                }}
              >
                impact
              </span>
            </div>
          ))}
        </div>
      )}

      {agent.agent_type === 'earnings' && (
        <>
          {agent.evidence_note && <EvidenceNote note={agent.evidence_note} />}
          {agent.earnings_tiles && agent.earnings_tiles.length > 0 && (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: 12,
              }}
            >
              {agent.earnings_tiles.map((t, i) => (
                <Stat key={i} label={t.label} value={t.value} tone={t.tone} />
              ))}
            </div>
          )}
        </>
      )}

      {agent.agent_type === 'industry' && agent.industry_meta && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ display: 'flex', gap: 16, marginBottom: 12, fontSize: 12 }}>
            {agent.industry_meta.cycle && (
              <span>
                <span style={{ color: 'var(--color-ink-3)' }}>Cycle:</span>{' '}
                <span style={{ color: 'var(--color-ink)', textTransform: 'capitalize' }}>
                  {agent.industry_meta.cycle.replace(/_/g, ' ')}
                </span>
              </span>
            )}
            {agent.industry_meta.moat != null && (
              <span>
                <span style={{ color: 'var(--color-ink-3)' }}>Moat:</span>{' '}
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink)' }}>
                  {agent.industry_meta.moat.toFixed(2)}
                </span>
              </span>
            )}
          </div>
          {agent.industry_competitors && agent.industry_competitors.length > 0 && (
            <div>
              {agent.industry_competitors.map((c, i) => (
                <div
                  key={i}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '180px 100px 1fr',
                    gap: 12,
                    fontSize: 12.5,
                    padding: '6px 0',
                    borderTop: '1px solid var(--color-rule-soft)',
                  }}
                >
                  <span style={{ color: 'var(--color-ink)' }}>{c.name}</span>
                  <span style={{ color: 'var(--color-ink-2)' }}>{c.threat}</span>
                  <span style={{ color: 'var(--color-ink-3)' }}>{c.note}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {agent.agent_type === 'valuation' && agent.valuation_tiles && agent.valuation_tiles.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
            gap: 12,
          }}
        >
          {agent.valuation_tiles.map((t, i) => (
            <Stat key={i} label={t.label} value={t.value} tone={t.tone} />
          ))}
        </div>
      )}

      {agent.agent_type === 'validation' && agent.validation_tiles && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 12,
          }}
        >
          {agent.validation_tiles.map((t, i) => (
            <Stat key={i} label={t.label} value={t.value} tone={t.tone} />
          ))}
        </div>
      )}
    </div>
  );
}
