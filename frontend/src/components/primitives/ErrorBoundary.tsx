import { Component, type ReactNode } from 'react';

interface Props {
  label: string; // which section this guards — shown in the fallback
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Section-level error boundary: a crash in one panel renders an inline error instead of
 * unmounting the entire page (the "blank screen" failure mode — e.g. one NaN price row once
 * took down the whole stock detail view). */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error(`[${this.props.label}] render crashed:`, error);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            border: '1px solid var(--color-rule)',
            borderLeft: '3px solid var(--color-neg-fg)',
            borderRadius: 6,
            padding: '12px 16px',
            marginBottom: 18,
            fontSize: 12,
            color: 'var(--color-ink-2)',
          }}
        >
          <strong style={{ color: 'var(--color-neg-fg)' }}>{this.props.label} failed to render</strong>
          <span style={{ color: 'var(--color-ink-3)' }}> — {this.state.error.message}</span>
        </div>
      );
    }
    return this.props.children;
  }
}
