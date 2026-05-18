import type { AgentLayout } from './AgentReports';

interface Props {
  value: AgentLayout;
  onChange: (v: AgentLayout) => void;
}

const OPTIONS: { value: AgentLayout; label: string }[] = [
  { value: 'tabs', label: 'Tabs' },
  { value: 'cards', label: 'Cards' },
  { value: 'narrative', label: 'Narrative' },
];

export default function AgentLayoutToggle({ value, onChange }: Props) {
  return (
    <div
      style={{
        display: 'inline-flex',
        border: '1px solid var(--color-rule)',
        borderRadius: 6,
        overflow: 'hidden',
        background: 'var(--color-surface)',
      }}
    >
      {OPTIONS.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            style={{
              padding: '5px 10px',
              fontSize: 11,
              fontFamily: 'var(--font-ui)',
              border: 'none',
              background: active ? 'var(--color-ink)' : 'transparent',
              color: active ? 'var(--color-surface)' : 'var(--color-ink-2)',
              cursor: 'pointer',
              fontWeight: 500,
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
