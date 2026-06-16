import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import type { ResearchNote } from '../../api/client';
import Card from '../primitives/Card';
import Markdown from '../primitives/Markdown';

/** The professional deliverable (5.1): the per-run research note, rendered as-is (it's Markdown
 * compiled deterministically by the backend) with a download. Collapsed by default — the panels
 * above are the live view; the note is the archival artifact. */
export default function ResearchNotePanel({ ticker, refreshKey }: { ticker: string; refreshKey: number }) {
  const [note, setNote] = useState<ResearchNote | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.notes.latest(ticker).then(setNote).catch(() => setNote(null));
  }, [ticker, refreshKey]);

  if (!note) return null;

  const download = () => {
    const blob = new Blob([note.note_md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${note.ticker}_research_note_${note.as_of}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Card padding={20} style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span
            style={{
              fontSize: 13,
              letterSpacing: '.1em',
              textTransform: 'uppercase',
              color: 'var(--color-ink-3)',
              fontWeight: 600,
            }}
          >
            Research note · {note.as_of}
          </span>
          {note.changes && note.changes.length > 0 && (
            <span style={{ fontSize: 11, color: 'var(--color-warn-fg)', marginLeft: 10 }}>
              {note.changes.length} change{note.changes.length !== 1 ? 's' : ''} since last note
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => setOpen(!open)}
            style={{
              padding: '4px 12px',
              borderRadius: 4,
              border: '1px solid var(--color-rule)',
              background: 'transparent',
              color: 'var(--color-ink-2)',
              cursor: 'pointer',
              fontSize: 12,
            }}
          >
            {open ? 'Collapse' : 'Read note'}
          </button>
          <button
            onClick={download}
            style={{
              padding: '4px 12px',
              borderRadius: 4,
              border: '1px solid var(--color-rule)',
              background: 'transparent',
              color: 'var(--color-ink-2)',
              cursor: 'pointer',
              fontSize: 12,
            }}
          >
            Download .md
          </button>
        </div>
      </div>
      {note.changes && note.changes.length > 0 && (
        <ul style={{ margin: '10px 0 0', paddingLeft: 18, fontSize: 12, color: 'var(--color-ink-2)' }}>
          {note.changes.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
      {open && (
        <div
          style={{
            marginTop: 14,
            padding: '4px 20px 16px',
            background: 'var(--color-surface-2)',
            borderRadius: 6,
            maxHeight: 680,
            overflowY: 'auto',
          }}
        >
          <Markdown source={note.note_md} />
        </div>
      )}
    </Card>
  );
}
