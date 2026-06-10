import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { CallHighlights, KeyMetric, NormalizedAgent, TileTone } from './agentView';

const TONE_COLOR: Record<TileTone, string> = {
  pos: 'var(--color-pos-fg)',
  neg: 'var(--color-neg-fg)',
  warn: 'var(--color-warn-fg)',
  muted: 'var(--color-ink-3)',
};

// ─── Emphasis helpers ───────────────────────────────────────────────────────
// Strict numeric regex: only match if there's a $ prefix, signed digit, or
// unit suffix (%, bps, B/M/K, x). Reject anything preceded by a letter/digit
// so "Q1", "Q2 '27", "H200", "FY26", "RTX 50", "2H26", "mid-70s" stay clean.
const NUMERIC_RX =
  /(?<![A-Za-z0-9])(?:\$[\d,]+(?:\.\d+)?[BMK]?|[+\-−][\d,]+(?:\.\d+)?(?:%|bps|[BMK]|x)?|[\d,]+(?:\.\d+)?(?:%|bps|[BMK]|x)(?!\w))(?:\s+(?:YoY|QoQ|YTD))?/g;

function emphasizeNumbers(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  NUMERIC_RX.lastIndex = 0;
  while ((m = NUMERIC_RX.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push(
      <mark
        key={'m' + i++}
        style={{
          background: 'var(--color-surface-2)',
          color: 'var(--color-ink)',
          padding: '0 4px',
          borderRadius: 3,
          fontFamily: 'var(--font-mono)',
          fontVariantNumeric: 'tabular-nums',
          fontSize: '.95em',
          fontWeight: 500,
        }}
      >
        {m[0]}
      </mark>
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts.length ? parts : [text];
}

// Split "Label: rest…" so the lede can be bolded.
function withLede(text: string): { lede: string | null; rest: string } {
  const idx = text.indexOf(':');
  if (idx > 0 && idx < 40 && idx < text.length - 2) {
    return { lede: text.slice(0, idx), rest: text.slice(idx + 1).trim() };
  }
  return { lede: null, rest: text };
}

function RichBullet({ text, accent }: { text: string; accent: string }) {
  const { lede, rest } = withLede(text);
  return (
    <li
      style={{
        paddingLeft: 0,
        marginBottom: 6,
        position: 'relative',
        lineHeight: 1.55,
        listStyle: 'none',
      }}
    >
      <span
        style={{
          position: 'absolute',
          left: -14,
          top: 8,
          width: 4,
          height: 4,
          borderRadius: 1,
          background: accent,
        }}
      />
      {lede && (
        <span style={{ fontWeight: 600, color: 'var(--color-ink)', marginRight: 6 }}>{lede}</span>
      )}
      <span style={{ color: 'var(--color-ink-2)' }}>{emphasizeNumbers(rest)}</span>
    </li>
  );
}

function CallHighlightCard({
  kicker,
  accent,
  bullets,
}: {
  kicker: string;
  accent: string;
  bullets: string[];
}) {
  if (!bullets || bullets.length === 0) return null;
  return (
    <div
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-rule)',
        borderRadius: 6,
        padding: '14px 18px 14px 28px',
        borderLeft: `2px solid ${accent}`,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '.1em',
          textTransform: 'uppercase',
          color: accent,
          marginBottom: 10,
          whiteSpace: 'nowrap',
        }}
      >
        {kicker}
      </div>
      <ul style={{ margin: 0, padding: 0, fontSize: 12.5, color: 'var(--color-ink-2)' }}>
        {bullets.map((b, i) => (
          <RichBullet key={i} text={b} accent={accent} />
        ))}
      </ul>
    </div>
  );
}

function ForwardGuidanceCallout({ text, tone }: { text: string; tone: string | null }) {
  if (!text) return null;
  return (
    <div
      style={{
        background: 'var(--color-pos-bg-soft)',
        border: '1px solid var(--color-rule)',
        borderLeft: '3px solid var(--color-pos-fg)',
        borderRadius: 6,
        padding: '16px 20px',
        marginBottom: 18,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 8,
          gap: 12,
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '.1em',
            textTransform: 'uppercase',
            color: 'var(--color-pos-fg)',
            whiteSpace: 'nowrap',
          }}
        >
          Forward guidance
        </span>
        {tone && (
          <span
            style={{
              fontSize: 10.5,
              color: 'var(--color-ink-3)',
              textTransform: 'capitalize',
              letterSpacing: '.02em',
            }}
          >
            Tone: {tone.toLowerCase()}
          </span>
        )}
      </div>
      <div
        style={{
          fontSize: 13.5,
          lineHeight: 1.65,
          color: 'var(--color-ink)',
          fontFamily: 'var(--font-serif)',
          textWrap: 'pretty' as const,
        }}
      >
        {emphasizeNumbers(text)}
      </div>
    </div>
  );
}

// ─── Tile / Stat ────────────────────────────────────────────────────────────

// A small ⓘ that reveals an explanation on hover/focus. Uses a portal + fixed positioning so the
// popover escapes any overflow-clipping parent, and a real styled box (not the flaky native title).
function InfoDot({ help }: { help: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [coords, setCoords] = useState<{ x: number; y: number; below: boolean } | null>(null);

  const open = () => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const below = r.top < 170; // not enough room above → drop the popover below the icon
    setCoords({ x: r.left + r.width / 2, y: below ? r.bottom : r.top, below });
  };
  const close = () => setCoords(null);

  return (
    <span
      ref={ref}
      onMouseEnter={open}
      onMouseLeave={close}
      onFocus={open}
      onBlur={close}
      tabIndex={0}
      role="button"
      aria-label={help}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 14,
        height: 14,
        borderRadius: '50%',
        border: `1px solid ${coords ? 'var(--color-ink)' : 'var(--color-ink-3)'}`,
        color: coords ? 'var(--color-ink)' : 'var(--color-ink-3)',
        fontSize: 9,
        fontWeight: 700,
        fontStyle: 'normal',
        textTransform: 'none',
        cursor: 'help',
        lineHeight: 1,
        flexShrink: 0,
      }}
    >
      i
      {coords &&
        createPortal(
          <div
            role="tooltip"
            style={{
              position: 'fixed',
              left: coords.x,
              top: coords.below ? coords.y + 10 : coords.y - 10,
              transform: coords.below ? 'translate(-50%, 0)' : 'translate(-50%, -100%)',
              maxWidth: 300,
              background: 'var(--color-surface)',
              border: '1px solid var(--color-rule)',
              color: 'var(--color-ink-2)',
              padding: '10px 12px',
              borderRadius: 6,
              fontSize: 12,
              fontWeight: 400,
              letterSpacing: 'normal',
              lineHeight: 1.5,
              whiteSpace: 'pre-line',
              textTransform: 'none',
              boxShadow: '0 8px 24px rgba(0,0,0,.22)',
              zIndex: 10000,
              pointerEvents: 'none',
            }}
          >
            {help}
          </div>,
          document.body
        )}
    </span>
  );
}

function Stat({ label, value, tone, help }: { label: string; value: string; tone?: TileTone; help?: string }) {
  return (
    <div style={{ padding: 12, background: 'var(--color-surface-2)', borderRadius: 6 }}>
      <div
        style={{
          fontSize: 10,
          letterSpacing: '.08em',
          textTransform: 'uppercase',
          color: 'var(--color-ink-3)',
          fontWeight: 600,
          marginBottom: 4,
          display: 'flex',
          alignItems: 'center',
          gap: 4,
        }}
      >
        {label}
        {help && <InfoDot help={help} />}
      </div>
      <div
        style={{
          fontSize: 16,
          fontFamily: 'var(--font-mono)',
          fontVariantNumeric: 'tabular-nums',
          color: tone ? TONE_COLOR[tone] : 'var(--color-ink)',
          fontStyle: tone === 'muted' ? 'italic' : undefined,
        }}
      >
        {value}
      </div>
    </div>
  );
}

// ─── Evidence note ──────────────────────────────────────────────────────────

function EvidenceNote({ note }: { note: NonNullable<NormalizedAgent['evidence_note']> }) {
  if (!note) return null;
  const sourceLabel: Record<string, string> = {
    transcript: 'earnings call transcript',
    management_guidance: 'management guidance',
    analyst_consensus: 'analyst consensus estimates',
    financial_trend_only: 'historical financials only — no transcript or guidance available',
    unavailable: 'no forward-looking sources available',
  };
  const label =
    (note.evidence_source && sourceLabel[note.evidence_source]) ||
    note.evidence_source ||
    'unavailable';
  return (
    <div
      style={{
        marginBottom: 12,
        padding: '10px 12px',
        borderLeft: '2px solid var(--color-watch-fg)',
        background: 'var(--color-watch-bg)',
        borderRadius: 4,
        fontSize: 12.5,
        color: 'var(--color-ink-2)',
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'baseline' }}>
        <span
          style={{
            color: 'var(--color-watch-fg)',
            fontWeight: 600,
            fontSize: 10,
            letterSpacing: '.08em',
            textTransform: 'uppercase',
            whiteSpace: 'nowrap',
          }}
        >
          Forward outlook
        </span>
        <span>Source: {label}</span>
      </div>
      {note.missing_data.length > 0 && (
        <div style={{ marginTop: 4, color: 'var(--color-ink-3)', fontSize: 11.5 }}>
          Missing: {note.missing_data.join(', ')}
        </div>
      )}
    </div>
  );
}

// ─── Key metrics table (enhanced with number emphasis in detail line) ──────

// Color coding:
//   beat / in_line → green (target met or exceeded)
//   close          → yellow (within ~5% of a warning threshold)
//   warning / miss → red (warning tripped, or significantly below target)
//   unknown        → gray
const VS_TARGET_TONE: Record<KeyMetric['vs_target'], TileTone | undefined> = {
  beat: 'pos',
  in_line: 'pos',
  close: 'warn',
  warning: 'neg',
  miss: 'neg',
  unknown: 'muted',
};

const TREND_GLYPH: Record<KeyMetric['trend'], string> = {
  up: '↑',
  down: '↓',
  flat: '→',
  unknown: '·',
};

function KeyMetricsBlock({ metrics }: { metrics: KeyMetric[] }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '.1em',
          textTransform: 'uppercase',
          color: 'var(--color-ink-3)',
          marginBottom: 10,
        }}
      >
        Key metrics to watch
      </div>
      <div style={{ border: '1px solid var(--color-rule)', borderRadius: 6, overflow: 'hidden' }}>
        {metrics.map((m, i) => {
          const tone = VS_TARGET_TONE[m.vs_target];
          const vsColor =
            tone === 'pos'
              ? 'var(--color-pos-fg)'
              : tone === 'neg'
                ? 'var(--color-neg-fg)'
                : tone === 'warn'
                  ? 'var(--color-warn-fg)'
                  : tone === 'muted'
                    ? 'var(--color-ink-3)'
                    : 'var(--color-ink)';
          return (
            <div
              key={i}
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 120px 90px 80px',
                gap: 16,
                alignItems: 'baseline',
                padding: '12px 16px',
                borderTop: i ? '1px solid var(--color-rule-soft)' : 'none',
                fontSize: 12.5,
              }}
            >
              <div>
                <div style={{ color: 'var(--color-ink)', fontWeight: 500, marginBottom: 2 }}>
                  {m.name}
                </div>
                {m.detail && (
                  <div style={{ fontSize: 11.5, color: 'var(--color-ink-3)', lineHeight: 1.5 }}>
                    {emphasizeNumbers(m.detail)}
                  </div>
                )}
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontVariantNumeric: 'tabular-nums',
                  color: vsColor,
                  textAlign: 'right',
                  fontSize: 13.5,
                  fontWeight: 500,
                }}
              >
                {m.value}
              </div>
              <div
                style={{
                  textAlign: 'center',
                  color: vsColor,
                  fontSize: 10.5,
                  textTransform: 'uppercase',
                  letterSpacing: '.06em',
                  fontWeight: 600,
                }}
              >
                <span style={{ marginRight: 4 }}>{TREND_GLYPH[m.trend]}</span>
                {m.vs_target.replace('_', ' ')}
              </div>
              <div
                style={{
                  fontSize: 10,
                  color: 'var(--color-ink-3)',
                  textTransform: 'uppercase',
                  letterSpacing: '.06em',
                  textAlign: 'right',
                }}
              >
                {m.source}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Earnings call highlights — sectioned grid ──────────────────────────────

function CallHighlightsBlock({ h }: { h: CallHighlights }) {
  const hasAny =
    h.segment_highlights.length ||
    h.key_themes.length ||
    h.one_time_items.length ||
    h.analyst_concerns.length;
  if (!hasAny) return null;

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 10,
          borderTop: '1px solid var(--color-rule-soft)',
          paddingTop: 16,
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '.1em',
            textTransform: 'uppercase',
            color: 'var(--color-ink-3)',
            whiteSpace: 'nowrap',
          }}
        >
          Earnings call
        </span>
        {h.management_tone && (
          <span
            style={{
              fontSize: 10.5,
              color: 'var(--color-ink-3)',
              textTransform: 'capitalize',
            }}
          >
            Tone: {h.management_tone.toLowerCase()}
          </span>
        )}
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: 10,
        }}
      >
        <CallHighlightCard
          kicker="Segment highlights"
          accent="var(--color-pos-fg)"
          bullets={h.segment_highlights}
        />
        <CallHighlightCard kicker="Themes" accent="var(--color-ink-2)" bullets={h.key_themes} />
        <CallHighlightCard
          kicker="One-time items"
          accent="var(--color-watch-fg)"
          bullets={h.one_time_items}
        />
        <CallHighlightCard
          kicker="Analyst Q&A"
          accent="var(--color-warn-fg)"
          bullets={h.analyst_concerns}
        />
      </div>
    </div>
  );
}

// ─── Dialectic: conviction + leaning illustrations ──────────────────────────

// Conviction is the agent's confidence in its OWN call (0–1), after weighing the other side —
// not a probability the stock rises. Banded + captioned so the number isn't a mystery.
function convictionBand(v: number): { label: string; color: string } {
  if (v < 0.4) return { label: 'Low', color: 'var(--color-neg-fg)' };
  if (v < 0.6) return { label: 'Moderate', color: 'var(--color-warn-fg)' };
  if (v < 0.8) return { label: 'High', color: 'var(--color-pos-fg)' };
  return { label: 'Very high', color: 'var(--color-pos-fg)' };
}

function ConvictionMeter({ value, help }: { value: number; help?: string }) {
  const band = convictionBand(value);
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 5 }}>
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--color-ink-3)' }}>
          Conviction
        </span>
        <span style={{ fontSize: 11.5 }}>
          <span style={{ color: band.color, fontWeight: 700 }}>{band.label}</span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-2)', marginLeft: 6 }}>
            {value.toFixed(2)}
          </span>
        </span>
      </div>
      <div style={{ position: 'relative', height: 6, borderRadius: 3, background: 'var(--color-surface-2)', overflow: 'hidden' }}>
        <div style={{ width: `${Math.round(value * 100)}%`, height: '100%', background: band.color }} />
      </div>
      {help && (
        <div style={{ fontSize: 11, color: 'var(--color-ink-3)', lineHeight: 1.5, marginTop: 6 }}>{help}</div>
      )}
    </div>
  );
}

const LEANINGS = ['strong_bear', 'bear', 'neutral', 'bull', 'strong_bull'];

// A 5-segment bear↔bull spectrum with the judge's landing spot highlighted.
function LeaningScale({ leaning }: { leaning: string }) {
  const idx = LEANINGS.indexOf(leaning);
  return (
    <div>
      <div style={{ display: 'flex', gap: 3, marginBottom: 4 }}>
        {LEANINGS.map((l, i) => {
          const active = i === idx;
          const color = i > 2 ? 'var(--color-pos-fg)' : i < 2 ? 'var(--color-neg-fg)' : 'var(--color-ink-2)';
          return (
            <div
              key={l}
              title={l.replace(/_/g, ' ')}
              style={{ flex: 1, height: 8, borderRadius: 2, background: active ? color : 'var(--color-surface-2)' }}
            />
          );
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9.5, letterSpacing: '.04em', textTransform: 'uppercase', color: 'var(--color-ink-3)' }}>
        <span>Bearish</span>
        <span>Bullish</span>
      </div>
    </div>
  );
}

// ─── Dialectic: bull / bear case points ─────────────────────────────────────

function CasePoints({
  kind,
  points,
  conviction,
}: {
  kind: 'bull' | 'bear';
  points: NonNullable<NormalizedAgent['case_points']>;
  conviction: number | null | undefined;
}) {
  const accent = kind === 'bull' ? 'var(--color-pos-fg)' : 'var(--color-neg-fg)';
  if (!points.length) return null;
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', marginBottom: 10 }}>
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: accent }}>
          {kind === 'bull' ? 'Bull points' : 'Bear points'}
        </span>
      </div>
      {conviction != null && (
        <div style={{ maxWidth: 320, marginBottom: 16 }}>
          <ConvictionMeter
            value={conviction}
            help={`The ${kind}'s honest confidence in this case — how strongly the evidence supports it.`}
          />
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {points.map((p, i) => (
          <div key={i} style={{ borderLeft: `2px solid ${accent}`, paddingLeft: 12 }}>
            <div style={{ fontSize: 13, color: 'var(--color-ink)', fontWeight: 500, marginBottom: 3 }}>
              {p.claim}
              {p.weight && (
                <span style={{ marginLeft: 8, fontSize: 9.5, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--color-ink-3)' }}>
                  {p.weight}
                </span>
              )}
            </div>
            {p.evidence && (
              <div style={{ fontSize: 12, color: 'var(--color-ink-2)', lineHeight: 1.55 }}>
                {emphasizeNumbers(p.evidence)}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Dialectic: judge synthesis ─────────────────────────────────────────────

const LEANING_TONE: Record<string, string> = {
  strong_bull: 'var(--color-pos-fg)',
  bull: 'var(--color-pos-fg)',
  neutral: 'var(--color-ink-2)',
  bear: 'var(--color-neg-fg)',
  strong_bear: 'var(--color-neg-fg)',
};
const ASSESS_TONE: Record<string, string> = {
  conceded: 'var(--color-neg-fg)',
  rebutted: 'var(--color-pos-fg)',
  partial: 'var(--color-warn-fg)',
  accepted: 'var(--color-pos-fg)',
  discounted: 'var(--color-ink-3)',
};

function Addressed({
  title,
  items,
}: {
  title: string;
  items: { point: string; assessment: string; reasoning: string }[];
}) {
  if (!items.length) return null;
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--color-ink-3)', marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {items.map((p, i) => (
          <div key={i}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
              <span style={{ fontSize: 9.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.05em', color: ASSESS_TONE[p.assessment] || 'var(--color-ink-3)', whiteSpace: 'nowrap' }}>
                {p.assessment}
              </span>
              <span style={{ fontSize: 12.5, color: 'var(--color-ink)' }}>{p.point}</span>
            </div>
            {p.reasoning && (
              <div style={{ fontSize: 12, color: 'var(--color-ink-2)', lineHeight: 1.5, marginTop: 2 }}>
                {emphasizeNumbers(p.reasoning)}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function JudgeBlock({ j }: { j: NonNullable<NormalizedAgent['judge_view']> }) {
  const tone = LEANING_TONE[j.leaning] || 'var(--color-ink-2)';
  return (
    <div>
      {/* Verdict card: leaning on a bear↔bull scale + a captioned conviction meter */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 20,
          padding: 16,
          marginBottom: 18,
          background: 'var(--color-surface-2)',
          borderRadius: 8,
        }}
      >
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--color-ink-3)', marginBottom: 6 }}>
            Leaning
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, color: tone, textTransform: 'capitalize', marginBottom: 10 }}>
            {j.leaning ? j.leaning.replace(/_/g, ' ') : '—'}
          </div>
          <LeaningScale leaning={j.leaning} />
        </div>
        {j.conviction != null && (
          <div>
            <ConvictionMeter
              value={j.conviction}
              help="How sure the judge is of this leaning after weighing the bear case — set by an anchored rubric off the count of unresolved bear points, not a gestalt guess. This is confidence in the call, not the odds the stock rises."
            />
            {j.unresolved_bear_points != null && j.total_bear_points != null && (
              <div style={{ fontSize: 11, color: 'var(--color-ink-3)', marginTop: 8, fontFamily: 'var(--font-mono)' }}>
                {j.unresolved_bear_points} of {j.total_bear_points} bear point
                {j.total_bear_points !== 1 ? 's' : ''} unresolved
                <span style={{ color: 'var(--color-ink-4, var(--color-ink-3))' }}>
                  {' '}— the rubric anchor for this conviction
                </span>
              </div>
            )}
          </div>
        )}
      </div>
      <Addressed title="Bear points addressed" items={j.bear_addressed} />
      <Addressed title="Bull points addressed" items={j.bull_addressed} />
      {j.kill_criteria.length > 0 ? (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--color-ink-3)', marginBottom: 8 }}>
            Kill criteria — dated, falsifiable
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {j.kill_criteria.map((k, i) => {
              const tone = k.would_confirm === 'bull' ? 'var(--color-pos-fg)' : 'var(--color-neg-fg)';
              return (
                <div key={i} style={{ borderLeft: `2px solid ${tone}`, paddingLeft: 12 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                    {k.by_date && (
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-ink-3)', whiteSpace: 'nowrap' }}>
                        {k.by_date}
                      </span>
                    )}
                    {k.would_confirm && (
                      <span style={{ fontSize: 9.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.05em', color: tone }}>
                        → {k.would_confirm}
                      </span>
                    )}
                    <span style={{ fontSize: 12.5, color: 'var(--color-ink)' }}>{k.prediction}</span>
                  </div>
                  {k.watch_metric && (
                    <div style={{ fontSize: 11.5, color: 'var(--color-ink-3)', marginTop: 2 }}>
                      Watch: {k.watch_metric}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        j.change_mind.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--color-ink-3)', marginBottom: 8 }}>
              What would change the call
            </div>
            <ul style={{ margin: 0, padding: 0 }}>
              {j.change_mind.map((c, i) => (
                <RichBullet key={i} text={c} accent="var(--color-ink-3)" />
              ))}
            </ul>
          </div>
        )
      )}
    </div>
  );
}

// ─── Main ───────────────────────────────────────────────────────────────────

interface Props {
  agent: NormalizedAgent;
}

export default function AgentBody({ agent }: Props) {
  return (
    <div>
      {agent.summary && (
        <p
          style={{
            fontSize: 13.5,
            lineHeight: 1.65,
            color: 'var(--color-ink)',
            margin: '0 0 14px',
            textWrap: 'pretty' as const,
            maxWidth: '68ch',
          }}
        >
          {agent.summary}
        </p>
      )}

      {agent.agent_type === 'news' && agent.news_items && agent.news_items.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {agent.news_items.map((h, i) => (
            <div
              key={i}
              style={{
                display: 'grid',
                gridTemplateColumns: '60px 1fr 70px 50px',
                gap: 12,
                alignItems: 'center',
                fontSize: 12.5,
                padding: '6px 0',
                borderTop: i ? '1px solid var(--color-rule-soft)' : 'none',
              }}
            >
              <span
                style={{
                  color: 'var(--color-ink-3)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                }}
              >
                {h.date}
              </span>
              <span style={{ color: 'var(--color-ink)' }}>{h.headline}</span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontVariantNumeric: 'tabular-nums',
                  color: h.tone === 'neg' ? 'var(--color-neg-fg)' : 'var(--color-pos-fg)',
                  textAlign: 'right',
                }}
              >
                {h.impact}
              </span>
              <span
                style={{
                  fontSize: 10,
                  color: 'var(--color-ink-3)',
                  textTransform: 'uppercase',
                  letterSpacing: '.06em',
                  textAlign: 'right',
                }}
              >
                impact
              </span>
            </div>
          ))}
        </div>
      )}

      {agent.agent_type === 'earnings' && (
        <>
          {agent.evidence_note && <EvidenceNote note={agent.evidence_note} />}

          {/* Tile strip — at-a-glance trend/quality metrics */}
          {agent.earnings_tiles && agent.earnings_tiles.length > 0 && (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: 12,
                marginBottom: 18,
              }}
            >
              {agent.earnings_tiles.map((t, i) => (
                <Stat key={i} label={t.label} value={t.value} tone={t.tone} help={t.help} />
              ))}
            </div>
          )}

          {/* Featured forward guidance callout (most important forward text) */}
          {agent.call_highlights?.forward_guidance_detail && (
            <ForwardGuidanceCallout
              text={agent.call_highlights.forward_guidance_detail}
              tone={agent.call_highlights.management_tone}
            />
          )}

          {/* Per-ticker key metrics with number emphasis in detail lines */}
          {agent.key_metrics && agent.key_metrics.length > 0 && (
            <KeyMetricsBlock metrics={agent.key_metrics} />
          )}

          {/* Sectioned highlight cards: segments / themes / one-time / Q&A */}
          {agent.call_highlights && <CallHighlightsBlock h={agent.call_highlights} />}
        </>
      )}

      {agent.agent_type === 'industry' && agent.industry_meta && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ display: 'flex', gap: 16, marginBottom: 12, fontSize: 12, alignItems: 'center' }}>
            {agent.industry_meta.cyclicality && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <span style={{ color: 'var(--color-ink-3)' }}>Demand:</span>{' '}
                <span style={{ color: 'var(--color-ink)', textTransform: 'capitalize' }}>
                  {agent.industry_meta.cyclicality.replace(/_/g, ' ')}
                </span>
                <InfoDot
                  help={
                    'How cyclical this industry’s demand actually is — judged per business-model archetype, so a cycle frame isn’t forced onto every stock:\n' +
                    '• Structural — demand is driven by secular adoption (platforms, secular growers); no meaningful cycle clock. Cycle shows "structural growth".\n' +
                    '• Moderately cyclical — demand has real macro sensitivity (e.g. ad spend tracks GDP).\n' +
                    '• Highly cyclical — boom/bust supply-demand cycles (memory, commodities); cycle position is the primary lens and peak earnings are a trap.'
                  }
                />
              </span>
            )}
            {agent.industry_meta.cycle && (
              <span>
                <span style={{ color: 'var(--color-ink-3)' }}>Cycle:</span>{' '}
                <span style={{ color: 'var(--color-ink)', textTransform: 'capitalize' }}>
                  {agent.industry_meta.cycle.replace(/_/g, ' ')}
                </span>
              </span>
            )}
            {agent.industry_meta.moat != null && (
              <span>
                <span style={{ color: 'var(--color-ink-3)' }}>Moat:</span>{' '}
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink)' }}>
                  {agent.industry_meta.moat.toFixed(2)}
                </span>
              </span>
            )}
          </div>
          {agent.industry_competitors && agent.industry_competitors.length > 0 && (
            <div>
              {agent.industry_competitors.map((c, i) => (
                <div
                  key={i}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '180px 100px 1fr',
                    gap: 12,
                    fontSize: 12.5,
                    padding: '6px 0',
                    borderTop: '1px solid var(--color-rule-soft)',
                  }}
                >
                  <span style={{ color: 'var(--color-ink)' }}>{c.name}</span>
                  <span style={{ color: 'var(--color-ink-2)' }}>{c.threat}</span>
                  <span style={{ color: 'var(--color-ink-3)' }}>{c.note}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {agent.agent_type === 'valuation' &&
        agent.valuation_tiles &&
        agent.valuation_tiles.length > 0 && (
          <>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: 12,
              }}
            >
              {agent.valuation_tiles.map((t, i) => (
                <Stat key={i} label={t.label} value={t.value} tone={t.tone} help={t.help} />
              ))}
            </div>
            {agent.valuation_note && (
              <div
                style={{
                  marginTop: 14,
                  padding: '10px 14px',
                  borderLeft: '2px solid var(--color-rule)',
                  fontSize: 12.5,
                  color: 'var(--color-ink-2)',
                  lineHeight: 1.55,
                }}
              >
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--color-ink-3)', marginRight: 8 }}>
                  vs Street
                </span>
                {emphasizeNumbers(agent.valuation_note)}
              </div>
            )}
          </>
        )}

      {(agent.agent_type === 'bull' || agent.agent_type === 'bear') &&
        agent.case_points &&
        agent.case_kind && (
          <CasePoints kind={agent.case_kind} points={agent.case_points} conviction={agent.case_conviction} />
        )}

      {agent.agent_type === 'judge' && agent.judge_view && <JudgeBlock j={agent.judge_view} />}

      {agent.agent_type === 'validation' && agent.validation_tiles && (
        <>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: 12,
            }}
          >
            {agent.validation_tiles.map((t, i) => (
              <Stat key={i} label={t.label} value={t.value} tone={t.tone} help={t.help} />
            ))}
          </div>
          {agent.validation_checks && agent.validation_checks.length > 0 ? (
            <ValidationChecks checks={agent.validation_checks} />
          ) : (
            <p style={{ fontSize: 12, color: 'var(--color-ink-3)', marginTop: 14 }}>
              No numeric claims were found to check in this run.
            </p>
          )}
        </>
      )}
    </div>
  );
}

const VERDICT_TONE: Record<string, string> = {
  CONFIRMED: 'var(--color-pos-fg)',
  CLOSE: 'var(--color-pos-fg)',
  CONTRADICTED: 'var(--color-neg-fg)',
  UNVERIFIABLE: 'var(--color-ink-3)',
};

function ValidationChecks({ checks }: { checks: NonNullable<NormalizedAgent['validation_checks']> }) {
  return (
    <div style={{ marginTop: 16 }}>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '.1em',
          textTransform: 'uppercase',
          color: 'var(--color-ink-3)',
          marginBottom: 8,
        }}
      >
        Claims checked — each re-derived against the database
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {checks.map((c, i) => {
          const tone = VERDICT_TONE[c.verdict] || 'var(--color-ink-3)';
          return (
            <div key={i} style={{ borderLeft: `2px solid ${tone}`, paddingLeft: 12 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: '.04em',
                    color: tone,
                  }}
                >
                  {c.verdict}
                </span>
                <span style={{ fontSize: 13, color: 'var(--color-ink)', fontWeight: 500 }}>
                  {c.claim}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    color: 'var(--color-ink-3)',
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                  }}
                >
                  · {c.agent}
                  {c.source === 'semantic' ? ' · semantic' : ''}
                </span>
              </div>
              {c.detail && (
                <div style={{ fontSize: 12, color: 'var(--color-ink-2)', marginTop: 2 }}>
                  {c.detail}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
