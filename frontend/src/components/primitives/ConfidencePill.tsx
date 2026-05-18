interface Props {
  confidence: string;
}

export default function ConfidencePill({ confidence }: Props) {
  const map: Record<string, { fg: string; label: string }> = {
    high: { fg: 'var(--color-pos-fg)', label: 'High confidence' },
    moderate: { fg: 'var(--color-warn-fg)', label: 'Moderate confidence' },
    low: { fg: 'var(--color-neg-fg)', label: 'Low confidence' },
  };
  const m = map[confidence] || { fg: 'var(--color-ink-2)', label: confidence };
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--color-ink-2)' }}>
      <span style={{ width: 6, height: 6, borderRadius: 3, background: m.fg }} />
      {m.label}
    </span>
  );
}
