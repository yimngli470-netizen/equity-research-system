import type { ReactNode, CSSProperties } from 'react';

export type BtnVariant = 'primary' | 'ghost' | 'quiet' | 'danger';
export type BtnSize = 'sm' | 'md' | 'lg';

interface Props {
  children: ReactNode;
  onClick?: () => void;
  variant?: BtnVariant;
  size?: BtnSize;
  disabled?: boolean;
  icon?: ReactNode;
  type?: 'button' | 'submit';
}

const sizes: Record<BtnSize, CSSProperties> = {
  sm: { padding: '5px 10px', fontSize: 12 },
  md: { padding: '7px 14px', fontSize: 12.5 },
  lg: { padding: '9px 18px', fontSize: 13 },
};

const variants: Record<BtnVariant, CSSProperties> = {
  primary: { background: 'var(--color-ink)', color: 'var(--color-surface)', border: '1px solid var(--color-ink)' },
  ghost: { background: 'transparent', color: 'var(--color-ink)', border: '1px solid var(--color-rule)' },
  quiet: { background: 'transparent', color: 'var(--color-ink-2)', border: '1px solid transparent' },
  danger: { background: 'transparent', color: 'var(--color-neg-fg)', border: '1px solid var(--color-rule)' },
};

export default function Btn({
  children,
  onClick,
  variant = 'primary',
  size = 'md',
  disabled,
  icon,
  type = 'button',
}: Props) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        ...sizes[size],
        ...variants[variant],
        borderRadius: 6,
        fontWeight: 500,
        fontFamily: 'var(--font-ui)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        letterSpacing: 0,
        transition: 'all .15s ease',
        whiteSpace: 'nowrap',
      }}
    >
      {icon}
      {children}
    </button>
  );
}
