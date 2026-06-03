import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type {
  AnalysisReport,
  Decision,
  ScreenRank,
  Stock,
  StockScore,
  ValuationResponse,
} from '../api/client';
import AgentLayoutToggle from '../components/detail/AgentLayoutToggle';
import AgentReports, { type AgentLayout } from '../components/detail/AgentReports';
import DecisionPanel from '../components/detail/DecisionPanel';
import DetailHeader from '../components/detail/DetailHeader';
import FinancialsTable from '../components/detail/FinancialsTable';
import PriceChart from '../components/detail/PriceChart';
import RiskFlagsPanel from '../components/detail/RiskFlagsPanel';
import ScoreBreakdownPanel from '../components/detail/ScoreBreakdownPanel';
import ScreenRankBar from '../components/detail/ScreenRankBar';
import SectionHeader from '../components/primitives/SectionHeader';
import { normalizeAgent } from '../components/detail/agentView';
import { runPipeline, usePipelineState } from '../state/pipelineTracker';

const AGENT_LAYOUT_KEY = 'agent-layout';
const AGENT_ORDER = ['news', 'earnings', 'industry', 'valuation', 'bull', 'bear', 'judge', 'validation'];

function loadAgentLayout(): AgentLayout {
  const v = localStorage.getItem(AGENT_LAYOUT_KEY);
  if (v === 'cards' || v === 'narrative' || v === 'tabs') return v;
  return 'tabs';
}

export default function StockDetail() {
  const { ticker: rawTicker } = useParams<{ ticker: string }>();
  const ticker = rawTicker?.toUpperCase() || '';
  const navigate = useNavigate();

  const [stock, setStock] = useState<Stock | null>(null);
  const [score, setScore] = useState<StockScore | null>(null);
  const [screenRank, setScreenRank] = useState<ScreenRank | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [valuation, setValuation] = useState<ValuationResponse | null>(null);
  const [reports, setReports] = useState<AnalysisReport[]>([]);
  const [loading, setLoading] = useState(true);

  const { running, message: pipelineMsg, warnings: pipelineWarnings } = usePipelineState(ticker);
  const [dataRefreshKey, setDataRefreshKey] = useState(0);
  const prevRunningRef = useRef(running);

  const [agentLayout, setAgentLayoutRaw] = useState<AgentLayout>(() => loadAgentLayout());
  const setAgentLayout = (v: AgentLayout) => {
    setAgentLayoutRaw(v);
    localStorage.setItem(AGENT_LAYOUT_KEY, v);
  };

  useEffect(() => {
    if (!ticker) return;
    loadAll();
    prevRunningRef.current = running;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker]);

  // Refetch when a backgrounded pipeline run finishes (running: true → false).
  // This handles the case where the user clicks Run, navigates away, and comes
  // back after the run already completed — they should see fresh numbers.
  useEffect(() => {
    if (!ticker) return;
    if (prevRunningRef.current && !running) {
      loadAll();
      setDataRefreshKey((v) => v + 1);
    }
    prevRunningRef.current = running;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, ticker]);

  async function loadAll() {
    setLoading(true);
    try {
      const [stockData, scoreData, decisionData, valuationData, reportsData, screenData] =
        await Promise.all([
          api.stocks.get(ticker),
          api.scores.latest(ticker).catch(() => null),
          api.decision.latest(ticker).catch(() => null),
          api.stocks.valuation(ticker).catch(() => null),
          api.analysis.list(ticker).catch(() => []),
          api.scoring.screen().catch(() => [] as ScreenRank[]),
        ]);
      setStock(stockData);
      setScore(scoreData);
      setDecision(decisionData);
      setValuation(valuationData);
      setReports(reportsData);
      setScreenRank(screenData.find((r) => r.ticker === ticker) ?? null);
    } catch {
      setStock(null);
    } finally {
      setLoading(false);
    }
  }

  function handleRunPipeline() {
    if (!ticker) return;
    // Fire-and-forget: the module-level tracker drives state. The
    // running→false transition handler above will refetch when it completes,
    // even if the user navigates away and returns.
    void runPipeline(ticker);
  }

  async function handleRemove() {
    if (!ticker || !window.confirm(`Remove ${ticker} from your watchlist?`)) return;
    await api.stocks.remove(ticker);
    navigate('/');
  }

  if (loading) {
    return <div style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>Loading…</div>;
  }
  if (!stock) {
    return (
      <div style={{ color: 'var(--color-neg-fg)', fontSize: 13 }}>
        Stock {ticker} not found.
      </div>
    );
  }

  // Build the agent list in canonical order, then normalize each.
  const reportsByType = new Map<string, AnalysisReport>();
  [...reports]
    .sort((a, b) => {
      const byRunDate = new Date(b.run_date).getTime() - new Date(a.run_date).getTime();
      if (byRunDate !== 0) return byRunDate;
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    })
    .forEach((r) => {
      if (!reportsByType.has(r.agent_type)) reportsByType.set(r.agent_type, r);
    });
  const agentsOrdered = AGENT_ORDER.flatMap((type) => {
    const r = reportsByType.get(type);
    return r ? [normalizeAgent(r)] : [];
  });

  return (
    <div>
      <DetailHeader
        stock={stock}
        valuation={valuation}
        onRunPipeline={handleRunPipeline}
        onRemove={handleRemove}
        running={running}
      />

      {pipelineMsg && (
        <div
          style={{
            background: 'var(--color-surface-2)',
            border: '1px solid var(--color-rule-soft)',
            borderRadius: 6,
            padding: '10px 14px',
            marginBottom: 18,
            fontSize: 12,
            color: 'var(--color-ink-2)',
          }}
        >
          {pipelineMsg}
        </div>
      )}

      {pipelineWarnings && pipelineWarnings.length > 0 && (
        <div
          style={{
            background: 'rgba(180, 120, 20, 0.10)',
            border: '1px solid rgba(180, 120, 20, 0.45)',
            borderRadius: 6,
            padding: '10px 14px',
            marginBottom: 18,
            fontSize: 12,
            color: 'var(--color-ink-2)',
          }}
        >
          <strong>⚠ Data coverage warnings</strong>
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {pipelineWarnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <PriceChart ticker={ticker} refreshKey={dataRefreshKey} />

      {decision && <DecisionPanel decision={decision} />}

      {screenRank && <ScreenRankBar rank={screenRank} />}

      {score && (
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 18, marginBottom: 18 }}>
          <ScoreBreakdownPanel score={score} />
          <RiskFlagsPanel flags={decision?.risk_flags || []} />
        </div>
      )}

      <SectionHeader
        kicker="Agents"
        title="AI Research"
        sub={
          agentsOrdered.length > 0
            ? `${agentsOrdered.length} agent${agentsOrdered.length !== 1 ? 's' : ''} reported${agentsOrdered.some((a) => a.agent_type === 'validation') ? ' · validation cross-checked claims against DB' : ''}`
            : 'No agent reports yet — click Run full pipeline above.'
        }
        actions={<AgentLayoutToggle value={agentLayout} onChange={setAgentLayout} />}
      />
      <AgentReports agents={agentsOrdered} layout={agentLayout} />

      <div style={{ marginTop: 28 }}>
        <FinancialsTable ticker={ticker} refreshKey={dataRefreshKey} />
      </div>
    </div>
  );
}
