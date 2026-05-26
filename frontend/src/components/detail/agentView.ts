// Maps the raw agent JSON (produced by backend) into a normalized view
// object that AgentBody can render. The backend's agent JSON shapes differ
// per agent type, so this layer absorbs that variability.

import type { AnalysisReport } from '../../api/client';

export type TileTone = 'pos' | 'neg' | 'warn' | 'muted';

export interface Tile {
  label: string;
  value: string;
  tone?: TileTone;
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
export interface KeyMetric {
  name: string;
  value: string;
  vs_target: 'beat' | 'miss' | 'in_line' | 'unknown';
  trend: 'up' | 'down' | 'flat' | 'unknown';
  source: 'transcript' | 'financials' | 'estimate' | 'unknown';
  detail: string;
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
  industry_meta?: { cycle: string | null; moat: number | null };
  industry_competitors?: { name: string; threat: string; note: string }[];
  valuation_tiles?: Tile[];
  validation_tiles?: Tile[];
}

const AGENT_MODEL: Record<string, string> = {
  news: 'Sonnet 4',
  earnings: 'Opus 4',
  industry: 'Opus 4',
  valuation: 'Opus 4',
  validation: 'Sonnet 4',
};

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
function trendTile(label: string, raw: string): Tile {
  const v = raw.toLowerCase();
  if (v === 'unknown') return { label, value: 'Unknown', tone: 'muted' };
  if (v === 'accelerating' || v === 'expanding') return { label, value: raw, tone: 'pos' };
  if (v === 'decelerating' || v === 'compressing') return { label, value: raw, tone: 'warn' };
  return { label, value: raw };
}

export function normalizeAgent(report: AnalysisReport): NormalizedAgent {
  const r = report.report as Record<string, unknown>;
  const agent_type = report.agent_type;
  const model = AGENT_MODEL[agent_type] || '';

  // The summary field exists on most agents but the validation agent puts an
  // object under summary. Pull a readable narrative from whichever field has one.
  let summary = '';
  if (typeof r.summary === 'string') summary = r.summary;
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
      });
    }

    // Quality score
    const eq = asNumber(r.earnings_quality_score);
    if (eq != null) {
      tiles.push({ label: 'Earnings quality', value: eq.toFixed(2), tone: eq >= 0.6 ? 'pos' : eq < 0.4 ? 'warn' : undefined });
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
    const allowedVsTarget = new Set(['beat', 'miss', 'in_line', 'unknown']);
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
    const comp = (r.competitive_position as Record<string, unknown>) || {};
    const moatStr = asString(comp.moat_strength).toLowerCase();
    const moatMap: Record<string, number> = { weak: 0.3, moderate: 0.55, strong: 0.85 };
    const moat = moatMap[moatStr] ?? asNumber(comp.moat_strength);
    base.industry_meta = { cycle, moat: moat ?? null };

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
    base.valuation_tiles = tiles;
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
  }

  return base;
}
