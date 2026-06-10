// Maps the raw agent JSON (produced by backend) into a normalized view
// object that AgentBody can render. The backend's agent JSON shapes differ
// per agent type, so this layer absorbs that variability.

import type { AnalysisReport } from '../../api/client';

export type TileTone = 'pos' | 'neg' | 'warn' | 'muted';

export interface Tile {
  label: string;
  value: string;
  tone?: TileTone;
  help?: string;   // optional explanation shown via an info icon on hover
}

export interface EvidenceNote {
  evidence_source: string | null; // e.g. "transcript" | "analyst_consensus" | "unavailable"
  missing_data: string[];         // e.g. ["earnings transcript", "forward guidance"]
}

// Transcript-derived content from the earnings call summary, surfaced in the UI.
// Empty arrays / null fields are filtered out at render time.
export interface CallHighlights {
  management_tone: string | null;
  forward_guidance_detail: string | null;
  segment_highlights: string[];
  key_themes: string[];
  one_time_items: string[];
  analyst_concerns: string[];
}

// One row in the earnings agent's per-ticker key-metrics report.
// 'close' = within ~5% of the warning threshold; 'warning' = past it.
// Metrics without a warning_threshold defined will only emit beat/in_line/miss/unknown.
export interface KeyMetric {
  name: string;
  value: string;
  vs_target: 'beat' | 'in_line' | 'close' | 'warning' | 'miss' | 'unknown';
  trend: 'up' | 'down' | 'flat' | 'unknown';
  source: 'transcript' | 'financials' | 'estimate' | 'unknown';
  detail: string;
}

export interface ValidationCheck {
  agent: string;        // which analyst agent made the claim
  claim: string;        // the specific claim that was checked
  verdict: 'CONFIRMED' | 'CLOSE' | 'CONTRADICTED' | 'UNVERIFIABLE' | string;
  detail: string;       // how it was resolved against the DB
  source: 'deterministic' | 'semantic' | string;
}

export interface NormalizedAgent {
  agent_type: string;
  model: string;
  run_date: string;
  version: number;
  cached: boolean;
  signal: string | null;
  summary: string;
  // Type-specific renderable data:
  news_items?: { date: string; headline: string; impact: string; tone: 'pos' | 'neg' | 'neut' }[];
  earnings_tiles?: Tile[];
  evidence_note?: EvidenceNote | null;  // earnings agent: surfaces "unknown"/missing-data signals
  call_highlights?: CallHighlights | null;  // earnings agent: transcript-derived sub-block
  key_metrics?: KeyMetric[];                // earnings agent: per-ticker watched metrics
  industry_meta?: { cycle: string | null; cyclicality: string | null; moat: number | null };
  industry_competitors?: { name: string; threat: string; note: string }[];
  valuation_tiles?: Tile[];
  valuation_note?: string | null;   // triangulation reconciliation vs the street (2.3)
  validation_tiles?: Tile[];
  validation_checks?: ValidationCheck[];   // the individual claims that were checked
  // Dialectic (bull / bear): evidence-cited points.
  case_kind?: 'bull' | 'bear';
  case_points?: { claim: string; evidence: string; weight: string }[];
  case_conviction?: number | null;
  // Dialectic (judge): the reconciled view.
  judge_view?: {
    leaning: string;
    conviction: number | null;
    unresolved_bear_points: number | null;
    total_bear_points: number | null;
    decisive_factors: string[];
    bear_addressed: { point: string; assessment: string; reasoning: string }[];
    bull_addressed: { point: string; assessment: string; reasoning: string }[];
    kill_criteria: { prediction: string; watch_metric: string; by_date: string; would_confirm: string }[];
    change_mind: string[]; // legacy fallback for older judge reports
  };
}

const AGENT_MODEL: Record<string, string> = {
  news: 'Sonnet 4',
  earnings: 'Opus 4',
  industry: 'Opus 4',
  valuation: 'Opus 4',
  bull: 'Opus 4',
  bear: 'Opus 4',
  judge: 'Opus 4',
  validation: 'Deterministic',
};

function toStrList(v: unknown): string[] {
  return Array.isArray(v) ? (v as unknown[]).map((x) => asString(x)).filter(Boolean) : [];
}

function asString(v: unknown): string {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  return String(v);
}

function asNumber(v: unknown): number | null {
  if (typeof v === 'number' && !isNaN(v)) return v;
  if (typeof v === 'string') {
    const n = parseFloat(v);
    return isNaN(n) ? null : n;
  }
  return null;
}

function fmtSignedPct(v: number): string {
  const s = (v * 100).toFixed(1);
  return v >= 0 ? `+${s}%` : `${s}%`;
}

function fmtPriceTile(v: number | null): string {
  if (v == null) return '—';
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// Map a trend/direction string from the agent to a tile + tone.
// 'unknown' renders muted (gray italic) so the user can tell the difference
// between "agent says decelerating" and "agent has no idea".
// Plain-language definitions for the trend labels, shown on the tile's info icon.
const REVENUE_TREND_HELP =
  'How the revenue GROWTH RATE itself is changing over recent quarters (not the level):\n' +
  '• Accelerating — the YoY growth rate is rising (e.g. +20% → +25%).\n' +
  '• Stable — the growth rate is holding roughly steady.\n' +
  '• Decelerating — still growing, but the growth rate is slowing each period.\n' +
  '• Unknown — not enough guidance/consensus/transcript evidence to classify.';
const MARGIN_TREND_HELP =
  'How profit MARGINS are moving over recent quarters:\n' +
  '• Expanding — margins widening (operating leverage / pricing power).\n' +
  '• Stable — margins roughly flat.\n' +
  '• Compressing — margins narrowing (cost or pricing pressure).\n' +
  '• Unknown — not enough evidence to classify.';

function trendKind(label: string): 'revenue' | 'margin' {
  return /margin/i.test(label) ? 'margin' : 'revenue';
}

function trendTile(label: string, raw: string): Tile {
  const v = raw.toLowerCase();
  const fwd = /^fwd/i.test(label);
  const base = trendKind(label) === 'margin' ? MARGIN_TREND_HELP : REVENUE_TREND_HELP;
  const help = fwd
    ? `Forward view — what to expect NEXT quarter, from management guidance, consensus, or the call.\n\n${base}`
    : `Trailing view — what recent reported quarters show.\n\n${base}`;
  if (v === 'unknown') return { label, value: 'Unknown', tone: 'muted', help };
  if (v === 'accelerating' || v === 'expanding') return { label, value: raw, tone: 'pos', help };
  if (v === 'decelerating' || v === 'compressing') return { label, value: raw, tone: 'warn', help };
  return { label, value: raw, help };
}

export function normalizeAgent(report: AnalysisReport): NormalizedAgent {
  const r = report.report as Record<string, unknown>;
  const agent_type = report.agent_type;
  const model = AGENT_MODEL[agent_type] || '';

  // The summary field exists on most agents but the validation agent puts an
  // object under summary. Pull a readable narrative from whichever field has one.
  let summary = '';
  if (typeof r.summary === 'string') summary = r.summary;
  else if (typeof r.thesis === 'string') summary = r.thesis;            // bull / bear
  else if (typeof r.synthesis === 'string') summary = r.synthesis;      // judge
  else if (typeof r.headline_assessment === 'string') summary = r.headline_assessment;
  else if (typeof r.cycle_assessment === 'string') summary = r.cycle_assessment;
  else if (agent_type === 'validation' && typeof r.summary === 'object' && r.summary) {
    const s = r.summary as Record<string, unknown>;
    const total = asNumber(s.total_checks) ?? 0;
    const conf = asNumber(s.confirmed) ?? 0;
    const contra = asNumber(s.contradicted) ?? 0;
    const unv = asNumber(s.unverifiable) ?? 0;
    const reliability = asNumber(s.reliability_score);
    const reliabilityTxt = reliability != null ? reliability.toFixed(2) : '—';
    summary = `${total} factual claims checked across the four analyst agents. ${conf} confirmed, ${contra} contradicted, ${unv} unverifiable. Reliability score ${reliabilityTxt}.`;
  }

  const base: NormalizedAgent = {
    agent_type,
    model,
    run_date: report.run_date,
    version: report.version,
    cached: false,
    signal: (r.signal as string) || (r.valuation_verdict as string) || null,
    summary,
  };

  if (agent_type === 'news') {
    const items = Array.isArray(r.items) ? (r.items as Record<string, unknown>[]) : [];
    base.news_items = items.slice(0, 4).map((it) => {
      const score = asNumber(it.impact_score) ?? 0;
      const dir = asString(it.impact_direction);
      const signed = dir === 'negative' ? -Math.abs(score) : Math.abs(score);
      return {
        date: report.run_date.slice(5),
        headline: asString(it.headline).slice(0, 90),
        impact: (signed >= 0 ? '+' : '') + signed.toFixed(2),
        tone: dir === 'negative' ? 'neg' : 'pos',
      };
    });
  }

  if (agent_type === 'earnings') {
    const tiles: Tile[] = [];

    // Latest quarter (string)
    if (typeof r.latest_quarter === 'string') {
      tiles.push({ label: 'Quarter', value: r.latest_quarter });
    }

    // Trend signals — historical
    const trend = (r.trend_analysis as Record<string, unknown>) || {};
    if (typeof trend.revenue_trend === 'string') {
      tiles.push(trendTile('Revenue trend', trend.revenue_trend));
    }
    if (typeof trend.margin_trend === 'string') {
      tiles.push(trendTile('Margin trend', trend.margin_trend));
    }

    // Forward outlook — the key place where 'unknown' lives now
    const outlook = (r.forward_outlook as Record<string, unknown>) || {};
    if (typeof outlook.revenue_direction === 'string') {
      tiles.push(trendTile('Fwd revenue', outlook.revenue_direction));
    }
    if (typeof outlook.margin_direction === 'string') {
      tiles.push(trendTile('Fwd margin', outlook.margin_direction));
    }

    // Beat / miss
    const beatMiss = (r.beat_miss_history as Record<string, unknown>) || {};
    const last4 = asNumber(beatMiss.last_4q_eps_beats);
    if (last4 != null) {
      tiles.push({ label: '4Q EPS beats', value: `${last4} / 4`, tone: last4 >= 3 ? 'pos' : last4 <= 1 ? 'warn' : undefined });
    }
    const avgSurprise = asNumber(beatMiss.avg_surprise_pct);
    if (avgSurprise != null) {
      tiles.push({
        label: 'Avg surprise',
        value: fmtSignedPct(avgSurprise),
        tone: avgSurprise >= 0 ? 'pos' : 'neg',
        help:
          'Average EPS surprise vs Wall Street consensus over the last 4 reported quarters — how far ' +
          'actual EPS landed above (+) or below (−) the estimate, on average. ' +
          'E.g. +11.7% means EPS came in ~11.7% above consensus. Computed deterministically from ' +
          'reported actuals vs estimates (earnings_events), not estimated by the model.',
      });
    }

    // Quality score
    const eq = asNumber(r.earnings_quality_score);
    if (eq != null) {
      tiles.push({
        label: 'Earnings quality',
        value: eq.toFixed(2),
        tone: eq >= 0.6 ? 'pos' : eq < 0.4 ? 'warn' : undefined,
        help:
          'The earnings analyst’s 0–1 read of HOW GOOD the earnings are beneath the headline number. ' +
          'Higher when growth is driven by real, recurring demand rather than one-time items, and when ' +
          'free cash flow tracks reported net income (cash-backed profits). Lower when results lean on ' +
          'one-offs, accruals, or FCF lags net income. A qualitative judgment by the earnings agent — ' +
          '≥0.60 strong, <0.40 a flag.',
      });
    }

    base.earnings_tiles = tiles;

    // Evidence note — surfaces "we don't have transcript/guidance" so the user
    // can see *why* the agent says unknown.
    const evidenceSource = typeof outlook.evidence_source === 'string' ? outlook.evidence_source : null;
    const missingRaw = Array.isArray(outlook.missing_data) ? (outlook.missing_data as unknown[]) : [];
    const missing = missingRaw.map((m) => asString(m)).filter(Boolean);
    if (evidenceSource === 'unavailable' || missing.length > 0 || evidenceSource === 'financial_trend_only') {
      base.evidence_note = { evidence_source: evidenceSource, missing_data: missing };
    } else {
      base.evidence_note = null;
    }

    // Call highlights — earnings call content the agent extracted. All fields
    // are optional; render only what's present.
    const ta = (r.transcript_analysis as Record<string, unknown>) || {};
    const toStrList = (v: unknown): string[] =>
      Array.isArray(v) ? (v as unknown[]).map(asString).filter(Boolean) : [];
    const highlights: CallHighlights = {
      management_tone: typeof ta.management_tone === 'string' ? ta.management_tone : null,
      forward_guidance_detail:
        typeof ta.forward_guidance_detail === 'string' && ta.forward_guidance_detail.trim()
          ? ta.forward_guidance_detail
          : null,
      segment_highlights: toStrList(ta.segment_highlights),
      key_themes: toStrList(ta.key_themes_from_call),
      one_time_items: toStrList(ta.one_time_items),
      analyst_concerns: toStrList(ta.analyst_concerns),
    };
    const hasAnyHighlight =
      highlights.management_tone ||
      highlights.forward_guidance_detail ||
      highlights.segment_highlights.length ||
      highlights.key_themes.length ||
      highlights.one_time_items.length ||
      highlights.analyst_concerns.length;
    base.call_highlights = hasAnyHighlight ? highlights : null;

    // Per-ticker key metrics — what the user actually wants to watch for this name.
    const kmRaw = Array.isArray(r.key_metrics) ? (r.key_metrics as Record<string, unknown>[]) : [];
    const allowedVsTarget = new Set(['beat', 'in_line', 'close', 'warning', 'miss', 'unknown']);
    const allowedTrend = new Set(['up', 'down', 'flat', 'unknown']);
    const allowedSource = new Set(['transcript', 'financials', 'estimate', 'unknown']);
    base.key_metrics = kmRaw
      .map((row): KeyMetric | null => {
        const name = asString(row.name);
        const value = asString(row.value);
        if (!name) return null;
        const vsRaw = asString(row.vs_target).toLowerCase();
        const trRaw = asString(row.trend).toLowerCase();
        const srcRaw = asString(row.source).toLowerCase();
        return {
          name,
          value: value || '—',
          vs_target: (allowedVsTarget.has(vsRaw) ? vsRaw : 'unknown') as KeyMetric['vs_target'],
          trend: (allowedTrend.has(trRaw) ? trRaw : 'unknown') as KeyMetric['trend'],
          source: (allowedSource.has(srcRaw) ? srcRaw : 'unknown') as KeyMetric['source'],
          detail: asString(row.detail),
        };
      })
      .filter((m): m is KeyMetric => m !== null);
  }

  if (agent_type === 'industry') {
    const cycle = typeof r.cycle_position === 'string' ? r.cycle_position : null;
    const cyclicality = typeof r.demand_cyclicality === 'string' ? r.demand_cyclicality : null;
    const comp = (r.competitive_position as Record<string, unknown>) || {};
    const moatStr = asString(comp.moat_strength).toLowerCase();
    const moatMap: Record<string, number> = { weak: 0.3, moderate: 0.55, strong: 0.85 };
    const moat = moatMap[moatStr] ?? asNumber(comp.moat_strength);
    base.industry_meta = { cycle, cyclicality, moat: moat ?? null };

    const competitors = Array.isArray(comp.key_competitors) ? (comp.key_competitors as string[]) : [];
    const risks = Array.isArray(comp.competitive_risks) ? (comp.competitive_risks as string[]) : [];
    base.industry_competitors = competitors.slice(0, 6).map((name, i) => ({
      name,
      threat: i < risks.length ? 'Mentioned' : '—',
      note: risks[i] ? String(risks[i]).slice(0, 80) : '—',
    }));
  }

  if (agent_type === 'valuation') {
    const tiles: Tile[] = [];
    const dcf = (r.dcf_analysis as Record<string, unknown>) || {};
    const target = (r.target_price_range as Record<string, unknown>) || {};
    const current = asNumber(r.current_price);
    const fair = asNumber(dcf.intrinsic_value_base) ?? asNumber(target.mid);
    const upside = asNumber(r.margin_of_safety);

    tiles.push({ label: 'DCF fair value', value: fmtPriceTile(fair) });
    tiles.push({ label: 'Current', value: fmtPriceTile(current) });
    if (upside != null) {
      // upside is sometimes given as percent number (e.g. 28.2 means 28.2%)
      const pct = Math.abs(upside) > 1 ? upside / 100 : upside;
      tiles.push({ label: 'Margin of safety', value: fmtSignedPct(pct), tone: pct >= 0 ? 'pos' : 'neg' });
    }
    if (typeof r.valuation_verdict === 'string') {
      tiles.push({ label: 'Verdict', value: r.valuation_verdict.replace(/_/g, ' ') });
    }

    // Triangulation vs the street (2.3): fair value, street target, divergence + justification.
    const tri = (r.triangulation as Record<string, unknown>) || {};
    const fv = asNumber(tri.your_fair_value);
    const street = asNumber(tri.street_mean_target);
    const div = asNumber(tri.divergence_pct);
    if (fv != null) tiles.push({ label: 'Your fair value', value: fmtPriceTile(fv) });
    if (street != null) tiles.push({ label: 'Street target', value: fmtPriceTile(street) });
    if (div != null) {
      tiles.push({ label: 'vs Street', value: fmtSignedPct(div), tone: div >= 0 ? 'pos' : 'neg' });
    }
    base.valuation_tiles = tiles;
    const justification = asString(tri.divergence_justification);
    const reconciliation = asString(tri.reconciliation);
    base.valuation_note = reconciliation || justification || null;
  }

  if (agent_type === 'bull' || agent_type === 'bear') {
    const listKey = agent_type === 'bull' ? 'bull_points' : 'bear_points';
    const weightKey = agent_type === 'bull' ? 'importance' : 'severity';
    const raw = Array.isArray(r[listKey]) ? (r[listKey] as Record<string, unknown>[]) : [];
    base.case_kind = agent_type;
    base.case_conviction = asNumber(r.conviction);
    base.case_points = raw
      .map((p) => ({
        claim: asString(p.claim),
        evidence: asString(p.evidence),
        weight: asString(p[weightKey]).toLowerCase(),
      }))
      .filter((p) => p.claim);
  }

  if (agent_type === 'judge') {
    const addressed = (v: unknown) =>
      Array.isArray(v)
        ? (v as Record<string, unknown>[])
            .map((p) => ({
              point: asString(p.point),
              assessment: asString(p.assessment).toLowerCase(),
              reasoning: asString(p.reasoning),
            }))
            .filter((p) => p.point)
        : [];
    const killCriteria = Array.isArray(r.kill_criteria)
      ? (r.kill_criteria as Record<string, unknown>[])
          .map((k) => ({
            prediction: asString(k.prediction),
            watch_metric: asString(k.watch_metric),
            by_date: asString(k.by_date),
            would_confirm: asString(k.would_confirm).toLowerCase(),
          }))
          .filter((k) => k.prediction)
      : [];
    base.judge_view = {
      leaning: asString(r.leaning).toLowerCase(),
      conviction: asNumber(r.conviction),
      unresolved_bear_points: asNumber(r.unresolved_bear_points),
      total_bear_points: asNumber(r.total_bear_points),
      decisive_factors: toStrList(r.decisive_factors),
      bear_addressed: addressed(r.bear_points_addressed),
      bull_addressed: addressed(r.bull_points_addressed),
      kill_criteria: killCriteria,
      change_mind: toStrList(r.what_would_change_my_mind),
    };
  }

  if (agent_type === 'validation') {
    const s = (r.summary as Record<string, unknown>) || {};
    const total = asNumber(s.total_checks) ?? 0;
    const conf = asNumber(s.confirmed) ?? 0;
    const contra = asNumber(s.contradicted) ?? 0;
    const reliability = asNumber(s.reliability_score);
    base.validation_tiles = [
      { label: 'Total checks', value: String(total) },
      { label: 'Confirmed', value: String(conf), tone: 'pos' },
      {
        label: 'Contradicted',
        value: String(contra),
        tone: contra > 0 ? 'warn' : undefined,
      },
      {
        label: 'Reliability',
        value: reliability != null ? reliability.toFixed(2) : '—',
      },
    ];

    const rawChecks = Array.isArray(r.checks) ? (r.checks as Record<string, unknown>[]) : [];
    base.validation_checks = rawChecks.map((c) => ({
      agent: asString(c.agent) || '—',
      claim: asString(c.claim) || asString(c.field) || 'Unspecified claim',
      verdict: asString(c.verdict).toUpperCase() || 'UNVERIFIABLE',
      detail: asString(c.detail),
      source: asString(c.source) || 'deterministic',
    }));
  }

  return base;
}
