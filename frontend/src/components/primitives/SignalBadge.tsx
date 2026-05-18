import { signalTone } from './tones';

export type SignalSize = 'xs' | 'sm' | 'md' | 'lg';
export type SignalVariant = 'subtle' | 'prominent';

interface Props {
  signal: string;
  size?: SignalSize;
  variant?: SignalVariant;
}

const sizes: Record<SignalSize, React.CSSProperties> = {
  xs: { padding: '1px 6px', fontSize: 10, letterSpacing: '.04em' },
  sm: { padding: '2px 8px', fontSize: 11, letterSpacing: '.04em' },
  md: { padding: '4px 10px', fontSize: 12, letterSpacing: '.04em' },
  lg: { padding: '6px 14px', fontSize: 13, letterSpacing: '.04em' },
};

export default function SignalBadge({ signal, size = 'sm', variant = 'subtle' }: Props) {
  const tone = signalTone(signal);
  const isProm = variant === 'prominent';
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        ...sizes[size],
        borderRadius: 4,
        fontWeight: 600,
        textTransform: 'uppercase',
        color: isProm ? 'var(--color-surface)' : tone.fg,
        background: isProm ? tone.fg : tone.bg,
        fontFamily: 'var(--font-ui)',
        whiteSpace: 'nowrap',
      }}
    >
      {tone.label}
    </span>
  );
}
