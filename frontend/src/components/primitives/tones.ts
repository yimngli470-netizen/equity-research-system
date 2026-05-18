// Tone-mapping helpers — keep these centralized so every component agrees
// on what "BUY" or "critical" looks like.

export interface Tone {
  fg: string;
  bg: string;
  label: string;
}

export function signalTone(signal: string): Tone {
  switch (signal) {
    case 'STRONG_BUY':
      return { fg: 'var(--color-pos-fg)', bg: 'var(--color-pos-bg)', label: 'Strong Buy' };
    case 'BUY':
      return { fg: 'var(--color-pos-fg)', bg: 'var(--color-pos-bg-soft)', label: 'Buy' };
    case 'HOLD':
      return { fg: 'var(--color-neut-fg)', bg: 'var(--color-neut-bg)', label: 'Hold' };
    case 'REDUCE':
      return { fg: 'var(--color-warn-fg)', bg: 'var(--color-warn-bg)', label: 'Reduce' };
    case 'SELL':
      return { fg: 'var(--color-neg-fg)', bg: 'var(--color-neg-bg)', label: 'Sell' };
    default:
      return { fg: 'var(--color-neut-fg)', bg: 'var(--color-neut-bg)', label: signal };
  }
}

export interface FlagTone extends Tone {
  dot: string;
}

export function flagTone(level: string): FlagTone {
  switch (level) {
    case 'critical':
      return { fg: 'var(--color-neg-fg)', bg: 'var(--color-neg-bg)', dot: 'var(--color-neg-fg)', label: 'Critical' };
    case 'major':
      return { fg: 'var(--color-warn-fg)', bg: 'var(--color-warn-bg)', dot: 'var(--color-warn-fg)', label: 'Major' };
    case 'watch':
      return { fg: 'var(--color-watch-fg)', bg: 'var(--color-watch-bg)', dot: 'var(--color-watch-fg)', label: 'Watch' };
    default:
      return { fg: 'var(--color-neut-fg)', bg: 'var(--color-neut-bg)', dot: 'var(--color-neut-fg)', label: level };
  }
}

export function scoreColor(v: number): string {
  if (v >= 0.7) return 'var(--color-pos-fg)';
  if (v >= 0.5) return 'var(--color-ink)';
  if (v >= 0.3) return 'var(--color-warn-fg)';
  return 'var(--color-neg-fg)';
}
