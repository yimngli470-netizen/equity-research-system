import { useCallback, useEffect, useState } from 'react';
import Card from '../primitives/Card';
import Btn from '../primitives/Btn';
import { api } from '../../api/client';
import type { KillSignal, KillSignalBuckets, KillSignalSeverity, KillVerdict } from '../../api/client';

interface Props {
  ticker: string;
  refreshKey?: number;
}

const SEVERITY_COLOR: Record<KillSignalSeverity, string> = {
  critical: 'var(--color-neg-fg)',
  high: 'var(--color-warn-fg)',
  medium: 'var(--color-ink-3)',
};

// The evaluator's read on the latest reported quarter. "undetermined" is shown, not hidden —
// it means the condition isn't checkable from earnings materials, which is worth knowing.
const VERDICT: Record<KillVerdict, { label: string; color: string }> = {
  tripped: { label: 'Tripped', color: 'var(--color-neg-fg)' },
  approaching: { label: 'Approaching', color: 'var(--color-warn-fg)' },
  not_tripped: { label: 'Clear', color: 'var(--color-pos-fg)' },
  undetermined: { label: 'Not checkable', color: 'var(--color-ink-3)' },
};

const SOURCE_LABEL: Record<KillSignal['source'], string> = {
  llm: 'AI',
  judge: 'Judge',
  manual: 'You',
};

const labelStyle = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: '.1em',
  textTransform: 'uppercase' as const,
  color: 'var(--color-ink-3)',
};

/** Standing kill signals — the conditions that would make you sell.
 *
 *  Three inputs feed this list: AI seeding at bootstrap, judge proposals after each run (they
 *  land as `candidates` needing review), and manual entry. Dismissing a judge proposal is NOT
 *  the same as deleting it — dismissal is remembered so the next judge run doesn't re-offer it,
 *  which is why the reject button on a candidate dismisses rather than deletes.
 */
export default function KillSignalsPanel({ ticker, refreshKey }: Props) {
  const [data, setData] = useState<KillSignalBuckets | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | 'new' | 'generate' | 'evaluate' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ signal: '', rationale: '', severity: 'high' as KillSignalSeverity });
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState({ signal: '', rationale: '', severity: 'high' as KillSignalSeverity });

  const load = useCallback(async () => {
    try {
      setData(await api.killSignals.list(ticker));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load kill signals');
    } finally {
      setLoading(false);
    }
  }, [ticker]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load, refreshKey]);

  const act = async (id: number | 'new' | 'generate' | 'evaluate', fn: () => Promise<unknown>) => {
    setBusy(id);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Action failed');
    } finally {
      setBusy(null);
    }
  };

  const submitNew = () => {
    const signal = draft.signal.trim();
    if (signal.length < 3) return;
    void act('new', async () => {
      await api.killSignals.add(ticker, {
        signal,
        rationale: draft.rationale.trim() || null,
        severity: draft.severity,
      });
      setDraft({ signal: '', rationale: '', severity: 'high' });
      setAdding(false);
    });
  };

  const startEdit = (s: KillSignal) => {
    setEditingId(s.id);
    setEditDraft({ signal: s.signal, rationale: s.rationale ?? '', severity: s.severity });
  };

  const submitEdit = (id: number) => {
    const signal = editDraft.signal.trim();
    if (signal.length < 3) return;
    void act(id, async () => {
      await api.killSignals.update(id, {
        signal,
        rationale: editDraft.rationale.trim() || null,
        severity: editDraft.severity,
      });
      setEditingId(null);
    });
  };

  if (loading) {
    return (
      <Card padding={20} style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 12.5, color: 'var(--color-ink-3)' }}>Loading kill signals…</div>
      </Card>
    );
  }

  const active = data?.active ?? [];
  const tripped = data?.tripped ?? [];
  const candidates = data?.candidates ?? [];
  const live = [...tripped, ...active];

  const row = (s: KillSignal, isCandidate: boolean) => {
    const editing = editingId === s.id;
    const disabled = busy === s.id;
    return (
      <div
        key={s.id}
        style={{
          padding: '12px 14px',
          borderLeft: `2px solid ${s.status === 'tripped' ? 'var(--color-neg-fg)' : SEVERITY_COLOR[s.severity]}`,
          background: s.status === 'tripped' ? 'var(--color-neg-bg, var(--color-surface-2))' : 'var(--color-surface-2)',
          borderRadius: 4,
          opacity: disabled ? 0.55 : 1,
        }}
      >
        {editing ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <textarea
              value={editDraft.signal}
              onChange={(e) => setEditDraft({ ...editDraft, signal: e.target.value })}
              rows={3}
              style={inputStyle}
            />
            <input
              value={editDraft.rationale}
              onChange={(e) => setEditDraft({ ...editDraft, rationale: e.target.value })}
              placeholder="Why this breaks the thesis (optional)"
              style={inputStyle}
            />
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <select
                value={editDraft.severity}
                onChange={(e) => setEditDraft({ ...editDraft, severity: e.target.value as KillSignalSeverity })}
                style={{ ...inputStyle, width: 110 }}
              >
                <option value="critical">critical</option>
                <option value="high">high</option>
                <option value="medium">medium</option>
              </select>
              <Btn size="sm" onClick={() => submitEdit(s.id)}>Save</Btn>
              <Btn size="sm" variant="quiet" onClick={() => setEditingId(null)}>Cancel</Btn>
            </div>
          </div>
        ) : (
          <>
            <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', marginBottom: 4 }}>
              <span
                style={{
                  ...labelStyle,
                  color: s.status === 'tripped' ? 'var(--color-neg-fg)' : SEVERITY_COLOR[s.severity],
                  whiteSpace: 'nowrap',
                }}
              >
                {s.status === 'tripped' ? 'Tripped' : s.severity}
              </span>
              <span style={{ fontSize: 12.5, lineHeight: 1.5, color: 'var(--color-ink)' }}>{s.signal}</span>
            </div>
            {s.rationale && (
              <div style={{ fontSize: 11.5, color: 'var(--color-ink-2)', lineHeight: 1.5, marginBottom: 4 }}>
                {s.rationale}
              </div>
            )}
            {s.evaluation && (
              <div
                style={{
                  fontSize: 11.5,
                  lineHeight: 1.5,
                  marginBottom: 6,
                  paddingLeft: 8,
                  borderLeft: `2px solid ${VERDICT[s.evaluation.verdict].color}`,
                }}
              >
                <span style={{ color: VERDICT[s.evaluation.verdict].color, fontWeight: 600 }}>
                  {VERDICT[s.evaluation.verdict].label}
                </span>
                {s.evaluation.period_end_date && (
                  <span style={{ color: 'var(--color-ink-3)' }}> · quarter ended {s.evaluation.period_end_date}</span>
                )}
                {s.evaluation.reasoning && (
                  <div style={{ color: 'var(--color-ink-2)', marginTop: 2 }}>{s.evaluation.reasoning}</div>
                )}
                {s.evaluation.evidence_quote && (
                  <div style={{ color: 'var(--color-ink-3)', marginTop: 2, fontStyle: 'italic' }}>
                    &ldquo;{s.evaluation.evidence_quote}&rdquo;
                  </div>
                )}
              </div>
            )}
            <div
              style={{
                display: 'flex',
                gap: 10,
                alignItems: 'center',
                flexWrap: 'wrap',
                fontSize: 10.5,
                color: 'var(--color-ink-3)',
              }}
            >
              <span>{SOURCE_LABEL[s.source]}</span>
              {s.by_date && <span>· by {s.by_date}</span>}
              {s.tripped_on && <span>· tripped {s.tripped_on}</span>}
              {s.tripped_note && <span>· {s.tripped_note}</span>}
              <span style={{ flex: 1 }} />
              {isCandidate ? (
                <>
                  <Btn size="sm" onClick={() => act(s.id, () => api.killSignals.update(s.id, { status: 'active' }))} disabled={disabled}>
                    Accept
                  </Btn>
                  <Btn size="sm" variant="ghost" onClick={() => startEdit(s)} disabled={disabled}>
                    Edit
                  </Btn>
                  {/* Dismiss, not delete: a dismissed proposal is never re-offered by the judge. */}
                  <Btn size="sm" variant="quiet" onClick={() => act(s.id, () => api.killSignals.update(s.id, { status: 'dismissed' }))} disabled={disabled}>
                    Dismiss
                  </Btn>
                </>
              ) : (
                <>
                  <Btn
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      act(s.id, () =>
                        api.killSignals.update(s.id, { status: s.status === 'tripped' ? 'active' : 'tripped' }),
                      )
                    }
                    disabled={disabled}
                  >
                    {s.status === 'tripped' ? 'Un-trip' : 'Trip manually'}
                  </Btn>
                  <Btn size="sm" variant="ghost" onClick={() => startEdit(s)} disabled={disabled}>
                    Edit
                  </Btn>
                  <Btn size="sm" variant="danger" onClick={() => act(s.id, () => api.killSignals.remove(s.id))} disabled={disabled}>
                    Remove
                  </Btn>
                </>
              )}
            </div>
          </>
        )}
      </div>
    );
  };

  return (
    <Card padding={24} style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6 }}>
        <h3 style={{ ...labelStyle, fontSize: 13, fontWeight: 600, margin: 0 }}>Kill signals</h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {tripped.length > 0 && (
            <span style={{ fontSize: 11, color: 'var(--color-neg-fg)', fontWeight: 600 }}>
              {tripped.length} tripped
            </span>
          )}
          <span style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>{active.length} active</span>
        </div>
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--color-ink-3)', marginBottom: 14, lineHeight: 1.5 }}>
        What would make you sell. Checked automatically against each reported quarter — a met condition
        trips itself, with the evidence shown. Also fed to the judge so it proposes new criteria rather
        than restating these.
      </div>

      {error && (
        <div style={{ fontSize: 12, color: 'var(--color-neg-fg)', marginBottom: 12 }}>{error}</div>
      )}

      {live.length === 0 && candidates.length === 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--color-ink-3)', marginBottom: 14 }}>
          No kill signals yet — add one, or generate a starting set from the business model.
        </div>
      )}

      {live.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
          {live.map((s) => row(s, false))}
        </div>
      )}

      {candidates.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ ...labelStyle, marginBottom: 8 }}>
            Proposed by the judge — {candidates.length} awaiting review
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {candidates.map((s) => row(s, true))}
          </div>
        </div>
      )}

      {adding ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <textarea
            value={draft.signal}
            onChange={(e) => setDraft({ ...draft, signal: e.target.value })}
            rows={3}
            autoFocus
            placeholder="Specific and falsifiable — e.g. 'Gross margin below 60% for two consecutive quarters'"
            style={inputStyle}
          />
          <input
            value={draft.rationale}
            onChange={(e) => setDraft({ ...draft, rationale: e.target.value })}
            placeholder="Why this breaks the thesis (optional)"
            style={inputStyle}
          />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <select
              value={draft.severity}
              onChange={(e) => setDraft({ ...draft, severity: e.target.value as KillSignalSeverity })}
              style={{ ...inputStyle, width: 110 }}
            >
              <option value="critical">critical</option>
              <option value="high">high</option>
              <option value="medium">medium</option>
            </select>
            <Btn size="sm" onClick={submitNew} disabled={busy === 'new' || draft.signal.trim().length < 3}>
              {busy === 'new' ? 'Adding…' : 'Add signal'}
            </Btn>
            <Btn size="sm" variant="quiet" onClick={() => setAdding(false)}>Cancel</Btn>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8 }}>
          <Btn size="sm" variant="ghost" onClick={() => setAdding(true)}>+ Add signal</Btn>
          <Btn
            size="sm"
            variant="quiet"
            onClick={() => act('generate', () => api.killSignals.generate(ticker, live.length > 0))}
            disabled={busy === 'generate'}
          >
            {busy === 'generate' ? 'Generating…' : 'Generate with AI'}
          </Btn>
          {/* Runs on its own during ingest; this forces a re-check of the current quarter. */}
          <Btn
            size="sm"
            variant="quiet"
            onClick={() => act('evaluate', () => api.killSignals.evaluate(ticker, true))}
            disabled={busy === 'evaluate'}
          >
            {busy === 'evaluate' ? 'Checking…' : 'Re-check now'}
          </Btn>
        </div>
      )}
    </Card>
  );
}

const inputStyle = {
  background: 'var(--color-surface)',
  border: '1px solid var(--color-rule)',
  borderRadius: 4,
  padding: '7px 9px',
  fontSize: 12.5,
  color: 'var(--color-ink)',
  fontFamily: 'inherit',
  width: '100%',
  boxSizing: 'border-box' as const,
};
