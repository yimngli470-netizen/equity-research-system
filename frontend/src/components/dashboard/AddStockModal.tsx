import { useEffect, useRef, useState } from 'react';
import Btn from '../primitives/Btn';
import { api } from '../../api/client';
import type { IrDiscoveryResult } from '../../api/client';

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
 * Add-stock modal. On submit it first runs IR auto-discovery (/discover-ir): crawl from the pasted
 * page, LLM-pick the quarterly-earnings-release page, and verify it by fetching a real release. The
 * result is shown inline — "✓ found earnings page" or "✗ needs manual config" — so a bad/overview URL
 * is caught here, not silently at the next earnings cycle. The user can then confirm-add, or add
 * anyway with the broad fallback config.
 */
export default function AddStockModal({ open, onClose, onSubmit }: Props) {
  const [ticker, setTicker] = useState('');
  const [irUrl, setIrUrl] = useState('');
  const [phase, setPhase] = useState<'form' | 'discovering' | 'result'>('form');
  const [result, setResult] = useState<IrDiscoveryResult | null>(null);
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const tickerRef = useRef<HTMLInputElement>(null);

  // Reset + focus when opened.
  useEffect(() => {
    if (open) {
      setTicker('');
      setIrUrl('');
      setPhase('form');
      setResult(null);
      setAdding(false);
      setErr(null);
      setTimeout(() => tickerRef.current?.focus(), 0);
    }
  }, [open]);

  const busy = phase === 'discovering' || adding;

  // Esc to close.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  function validate(): { t: string; url: string } | null {
    const t = ticker.trim().toUpperCase();
    const url = irUrl.trim();
    if (!t) {
      setErr('Enter a ticker.');
      return null;
    }
    if (!/^https?:\/\//i.test(url)) {
      setErr('An Investor Relations earnings page URL (https://…) is required.');
      return null;
    }
    return { t, url };
  }

  // Step 1: run discovery and show the verdict inline (does not add the stock yet).
  async function runDiscovery() {
    const v = validate();
    if (!v) return;
    setErr(null);
    setPhase('discovering');
    try {
      const res = await api.stocks.discoverIr({ ticker: v.t, seed_url: v.url });
      setResult(res);
      setPhase('result');
    } catch (e) {
      // Discovery endpoint itself errored — let the user add anyway with the fallback config.
      setResult({
        status: 'needs_attention',
        ir_url: null,
        strategy_type: null,
        strategy_pattern: null,
        artifact_type: null,
        sample_url: null,
        sample_chars: 0,
        confidence: null,
        message:
          (e instanceof Error ? e.message : 'Auto-discovery failed') +
          '. You can still add with the pasted URL and a broad fallback config.',
      });
      setPhase('result');
    }
  }

  // Step 2: actually add the stock. If discovery succeeded, the verified strategy is already in the
  // registry and the add won't overwrite it; otherwise the backend writes the broad fallback config.
  async function confirmAdd() {
    const v = validate();
    if (!v) return;
    setAdding(true);
    setErr(null);
    try {
      await onSubmit(v.t, v.url);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to add stock');
      setAdding(false);
    }
  }

  const ok = result?.status === 'ok';

  return (
    <div
      onClick={() => !busy && onClose()}
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
          Paste any Investor Relations page — we'll find the quarterly earnings page from it and verify
          it before adding.
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>Ticker</label>
          <input
            ref={tickerRef}
            value={ticker}
            disabled={busy}
            onChange={(e) => {
              setTicker(e.target.value);
              if (phase === 'result') setPhase('form');
            }}
            onKeyDown={(e) => e.key === 'Enter' && runDiscovery()}
            placeholder="e.g. NOW"
            style={{ ...inputStyle, textTransform: 'uppercase' }}
          />
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>Investor Relations page URL</label>
          <input
            value={irUrl}
            disabled={busy}
            onChange={(e) => {
              setIrUrl(e.target.value);
              if (phase === 'result') setPhase('form');
            }}
            onKeyDown={(e) => e.key === 'Enter' && runDiscovery()}
            placeholder="https://www.servicenow.com/company/investor-relations.html"
            style={inputStyle}
          />
        </div>

        {phase === 'discovering' && (
          <div style={{ fontSize: 12, color: 'var(--color-ink-2)', marginBottom: 14 }}>
            Finding the earnings page and verifying a real release… this can take ~20s.
          </div>
        )}

        {phase === 'result' && result && (
          <div
            style={{
              fontSize: 12,
              lineHeight: 1.5,
              marginBottom: 14,
              padding: '10px 12px',
              borderRadius: 6,
              border: '1px solid var(--color-rule)',
              background: ok ? 'var(--color-pos-bg, #ecfdf5)' : 'var(--color-neg-bg)',
              color: ok ? 'var(--color-pos-fg, #065f46)' : 'var(--color-neg-fg)',
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 3 }}>
              {ok ? '✓ Found earnings page' : '✗ Needs manual config'}
            </div>
            <div>{result.message}</div>
            {ok && result.ir_url && (
              <div style={{ marginTop: 4, opacity: 0.85, wordBreak: 'break-all' }}>{result.ir_url}</div>
            )}
          </div>
        )}

        {err && (
          <div style={{ fontSize: 12, color: 'var(--color-neg-fg)', marginBottom: 14 }}>{err}</div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 6 }}>
          <Btn variant="ghost" size="md" onClick={onClose} disabled={busy}>
            Cancel
          </Btn>

          {phase !== 'result' && (
            <Btn variant="primary" size="md" onClick={runDiscovery} disabled={busy}>
              {phase === 'discovering' ? 'Finding…' : 'Find earnings page'}
            </Btn>
          )}

          {phase === 'result' && ok && (
            <Btn variant="primary" size="md" onClick={confirmAdd} disabled={adding}>
              {adding ? 'Adding…' : 'Add ticker'}
            </Btn>
          )}

          {phase === 'result' && !ok && (
            <>
              <Btn variant="ghost" size="md" onClick={runDiscovery} disabled={adding}>
                Retry
              </Btn>
              <Btn variant="primary" size="md" onClick={confirmAdd} disabled={adding}>
                {adding ? 'Adding…' : 'Add anyway'}
              </Btn>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
