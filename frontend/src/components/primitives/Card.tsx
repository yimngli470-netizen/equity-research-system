import type { ReactNode, CSSProperties } from 'react';

interface Props {
  children: ReactNode;
  padding?: number;
  style?: CSSProperties;
  className?: string;
  onClick?: () => void;
  hover?: boolean;
}

export default function Card({ children, padding = 20, style, className = '', onClick, hover = false }: Props) {
  return (
    <div
      onClick={onClick}
      className={className}
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-rule)',
        borderRadius: 8,
        padding,
        cursor: onClick ? 'pointer' : undefined,
        transition: hover ? 'border-color .15s ease' : undefined,
        ...style,
      }}
      onMouseEnter={
        hover
          ? (e) => {
              (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--color-ink-3)';
            }
          : undefined
      }
      onMouseLeave={
        hover
          ? (e) => {
              (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--color-rule)';
            }
          : undefined
      }
    >
      {children}
    </div>
  );
}
