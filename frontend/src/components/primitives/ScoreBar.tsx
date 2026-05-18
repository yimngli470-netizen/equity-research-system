import { scoreColor } from './tones';

interface Props {
  value: number;
  height?: number;
  showVal?: boolean;
  label?: string;
}

export default function ScoreBar({ value, height = 6, showVal = true, label }: Props) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%' }}>
      {label && (
        <span style={{ flex: '0 0 96px', fontSize: 12, color: 'var(--color-ink-2)' }}>{label}</span>
      )}
      <div
        style={{
          flex: 1,
          minWidth: 0,
          position: 'relative',
          height,
          background: 'var(--color-rule-soft)',
          borderRadius: height / 2,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: `${pct}%`,
            background: scoreColor(value),
            borderRadius: height / 2,
            transition: 'width .4s ease',
          }}
        />
      </div>
      {showVal && (
        <span
          style={{
            flex: '0 0 32px',
            textAlign: 'right',
            fontFamily: 'var(--font-mono)',
            fontVariantNumeric: 'tabular-nums',
            fontSize: 12,
            color: 'var(--color-ink)',
          }}
        >
          {value.toFixed(2)}
        </span>
      )}
    </div>
  );
}
