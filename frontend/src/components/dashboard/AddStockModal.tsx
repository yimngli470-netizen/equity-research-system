import { useEffect, useRef, useState } from 'react';
import Btn from '../primitives/Btn';

interface Props {
  open: boolean;
  onClose: () => void;
  // Resolve to throw on failure (the modal shows the message and stays open).
  onSubmit: (ticker: string, irUrl: string) => Promise<void>;
}

const inputStyle: React.CSSProperties = {
  border: '1px solid var(--color-rule)',
  background: 'var(--color-surface)',
  color: 'var(--color-ink)',
  padding: '8px 12px',
  borderRadius: 6,
  fontSize: 13,
  width: '100%',
  fontFamily: 'var(--font-ui)',
  outline: 'none',
  boxSizing: 'border-box',
};

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 11.5,
  fontWeight: 600,
  color: 'var(--color-ink-2)',
  marginBottom: 5,
  letterSpacing: 0.2,
};

/**
 * Single add-stock modal with two fields (ticker + IR URL) — replaces the old pair of sequential
 * window.prompt() dialogs. The IR URL is required (auto-discovery was removed because it guessed the
 * wrong domain too often), so both fields live in one form and validate together before submit.
 */
export default function AddStockModal({ open, onClose, onSubmit }: Props) {
  const [ticker, setTicker] = useState('');
  const [irUrl, setIrUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const tickerRef = useRef<HTMLInputElement>(null);

  // Reset + focus when opened.
  useEffect(() => {
    if (open) {
      setTicker('');
      setIrUrl('');
      setErr(null);
      setSubmitting(false);
      setTimeout(() => tickerRef.current?.focus(), 0);
    }
  }, [open]);

  // Esc to close.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, submitting, onClose]);

  if (!open) return null;

  async function submit() {
    const t = ticker.trim().toUpperCase();
    const url = irUrl.trim();
    if (!t) {
      setErr('Enter a ticker.');
      return;
    }
    if (!/^https?:\/\//i.test(url)) {
      setErr('An Investor Relations earnings page URL (https://…) is required.');
      return;
    }
    setSubmitting(true);
    setErr(null);
    try {
      await onSubmit(t, url);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to add stock');
      setSubmitting(false);
    }
  }

  return (
    <div
      onClick={() => !submitting && onClose()}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.38)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 50,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-rule)',
          borderRadius: 10,
          padding: 22,
          width: 460,
          maxWidth: 'calc(100vw - 32px)',
          boxShadow: '0 12px 40px rgba(0,0,0,0.18)',
          fontFamily: 'var(--font-ui)',
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--color-ink)', marginBottom: 4 }}>
          Add a ticker
        </div>
        <div style={{ fontSize: 12, color: 'var(--color-ink-2)', marginBottom: 18 }}>
          The Investor Relations earnings page is required — it's where transcripts are fetched from.
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>Ticker</label>
          <input
            ref={tickerRef}
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
            placeholder="e.g. NOW"
            style={{ ...inputStyle, textTransform: 'uppercase' }}
          />
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>Investor Relations earnings page URL</label>
          <input
            value={irUrl}
            onChange={(e) => setIrUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
            placeholder="https://www.servicenow.com/company/investor-relations.html"
            style={inputStyle}
          />
        </div>

        {err && (
          <div style={{ fontSize: 12, color: 'var(--color-neg-fg)', marginBottom: 14 }}>{err}</div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 6 }}>
          <Btn variant="ghost" size="md" onClick={onClose} disabled={submitting}>
            Cancel
          </Btn>
          <Btn variant="primary" size="md" onClick={submit} disabled={submitting}>
            {submitting ? 'Adding…' : 'Add ticker'}
          </Btn>
        </div>
      </div>
    </div>
  );
}
