import { useState } from 'react';
import AgentBody from './AgentBody';
import Card from '../primitives/Card';
import type { NormalizedAgent } from './agentView';

export type AgentLayout = 'tabs' | 'cards' | 'narrative';

interface Props {
  agents: NormalizedAgent[];
  layout: AgentLayout;
}

export default function AgentReports({ agents, layout }: Props) {
  if (agents.length === 0) {
    return (
      <Card padding={20}>
        <div style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>
          No agent reports yet. Click "Run full pipeline" to generate.
        </div>
      </Card>
    );
  }
  if (layout === 'cards') return <CardsLayout agents={agents} />;
  if (layout === 'narrative') return <NarrativeLayout agents={agents} />;
  return <TabsLayout agents={agents} />;
}

function AgentHeader({ a }: { a: NormalizedAgent }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 10,
        flexWrap: 'wrap',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: 'var(--color-ink)',
            textTransform: 'capitalize',
          }}
        >
          {a.agent_type}
        </span>
        {a.signal && (
          <span
            style={{
              fontSize: 10,
              letterSpacing: '.04em',
              fontWeight: 600,
              padding: '1px 7px',
              borderRadius: 3,
              background: 'var(--color-surface-2)',
              color: 'var(--color-ink-2)',
              textTransform: 'uppercase',
            }}
          >
            {a.signal.replace(/_/g, ' ')}
          </span>
        )}
      </div>
      <div style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
        {a.model} · {a.run_date} · v{a.version}
      </div>
    </div>
  );
}

function TabsLayout({ agents }: { agents: NormalizedAgent[] }) {
  const [active, setActive] = useState(agents[0].agent_type);
  const cur = agents.find((a) => a.agent_type === active) ?? agents[0];
  return (
    <Card padding={0} style={{ overflow: 'hidden' }}>
      <div style={{ display: 'flex', borderBottom: '1px solid var(--color-rule)' }}>
        {agents.map((a) => {
          const isActive = a.agent_type === active;
          return (
            <button
              key={a.agent_type}
              onClick={() => setActive(a.agent_type)}
              style={{
                flex: 1,
                background: 'transparent',
                border: 'none',
                padding: '16px 12px',
                borderBottom: isActive ? '2px solid var(--color-ink)' : '2px solid transparent',
                marginBottom: -1,
                color: isActive ? 'var(--color-ink)' : 'var(--color-ink-3)',
                fontWeight: isActive ? 600 : 500,
                fontSize: 12.5,
                fontFamily: 'var(--font-ui)',
                cursor: 'pointer',
                textTransform: 'capitalize',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <span>{a.agent_type}</span>
              <span
                style={{
                  fontSize: 10,
                  color: 'var(--color-ink-3)',
                  letterSpacing: '.04em',
                  fontWeight: 500,
                }}
              >
                {a.model} · v{a.version}
              </span>
            </button>
          );
        })}
      </div>
      <div style={{ padding: 24 }}>
        <AgentBody agent={cur} />
      </div>
    </Card>
  );
}

function CardsLayout({ agents }: { agents: NormalizedAgent[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {agents.map((a) => (
        <Card key={a.agent_type} padding={20}>
          <AgentHeader a={a} />
          <AgentBody agent={a} />
        </Card>
      ))}
    </div>
  );
}

function NarrativeLayout({ agents }: { agents: NormalizedAgent[] }) {
  return (
    <Card padding={32}>
      <div style={{ maxWidth: '68ch', margin: '0 auto' }}>
        <div
          style={{
            fontSize: 11,
            letterSpacing: '.14em',
            textTransform: 'uppercase',
            color: 'var(--color-ink-3)',
            fontWeight: 600,
            marginBottom: 6,
            textAlign: 'center',
          }}
        >
          Research Note
        </div>
        <h3
          style={{
            fontSize: 22,
            fontWeight: 500,
            color: 'var(--color-ink)',
            letterSpacing: '-.01em',
            textAlign: 'center',
            margin: '0 0 28px',
          }}
        >
          Synthesis across {agents.length} agents
        </h3>
        {agents.map((a, i) => (
          <div key={a.agent_type} style={{ marginBottom: 28 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8 }}>
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: 'var(--color-ink-3)',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                {String(i + 1).padStart(2, '0')}
              </span>
              <h4
                style={{
                  fontSize: 15,
                  fontWeight: 600,
                  color: 'var(--color-ink)',
                  margin: 0,
                  textTransform: 'capitalize',
                  letterSpacing: '-.005em',
                }}
              >
                {a.agent_type}
              </h4>
              <span style={{ fontSize: 10.5, color: 'var(--color-ink-3)' }}>
                {a.model} · {a.run_date}
              </span>
            </div>
            <p
              style={{
                fontSize: 14.5,
                lineHeight: 1.7,
                color: 'var(--color-ink)',
                margin: 0,
                textWrap: 'pretty' as const,
                fontFamily: 'var(--font-serif)',
              }}
            >
              {a.summary || '(no summary)'}
            </p>
          </div>
        ))}
      </div>
    </Card>
  );
}
