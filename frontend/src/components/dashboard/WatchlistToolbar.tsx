import Btn from '../primitives/Btn';

export type Layout = 'table' | 'grid';
export type SortBy = 'score' | 'ticker' | 'change' | 'flags';

interface Props {
  query: string;
  setQuery: (v: string) => void;
  sortBy: SortBy;
  setSortBy: (v: SortBy) => void;
  layout: Layout;
  setLayout: (v: Layout) => void;
  onAdd: () => void;
}

interface SegmentedProps<T extends string> {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}

function Segmented<T extends string>({ value, onChange, options }: SegmentedProps<T>) {
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
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            style={{
              padding: '6px 12px',
              fontSize: 12,
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

export default function WatchlistToolbar({
  query,
  setQuery,
  sortBy,
  setSortBy,
  layout,
  setLayout,
  onAdd,
}: Props) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        marginBottom: 16,
        flexWrap: 'wrap',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by ticker or name…"
          style={{
            border: '1px solid var(--color-rule)',
            background: 'var(--color-surface)',
            color: 'var(--color-ink)',
            padding: '7px 12px',
            borderRadius: 6,
            fontSize: 12.5,
            width: 240,
            fontFamily: 'var(--font-ui)',
            outline: 'none',
          }}
        />
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortBy)}
          style={{
            border: '1px solid var(--color-rule)',
            background: 'var(--color-surface)',
            color: 'var(--color-ink)',
            padding: '7px 10px',
            borderRadius: 6,
            fontSize: 12.5,
            fontFamily: 'var(--font-ui)',
            outline: 'none',
          }}
        >
          <option value="score">Sort: composite score</option>
          <option value="ticker">Sort: ticker A→Z</option>
          <option value="change">Sort: today's change</option>
          <option value="flags">Sort: open flags</option>
        </select>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Segmented<Layout>
          value={layout}
          onChange={setLayout}
          options={[
            { value: 'table', label: 'Table' },
            { value: 'grid', label: 'Grid' },
          ]}
        />
        <Btn variant="primary" size="md" onClick={onAdd} icon={<span style={{ fontSize: 14, lineHeight: 1 }}>+</span>}>
          Add ticker
        </Btn>
      </div>
    </div>
  );
}
