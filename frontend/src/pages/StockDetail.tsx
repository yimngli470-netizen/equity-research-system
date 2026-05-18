import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type {
  AnalysisReport,
  Decision,
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
import SectionHeader from '../components/primitives/SectionHeader';
import { normalizeAgent } from '../components/detail/agentView';

const AGENT_LAYOUT_KEY = 'agent-layout';
const AGENT_ORDER = ['news', 'earnings', 'industry', 'valuation', 'validation'];

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
  const [decision, setDecision] = useState<Decision | null>(null);
  const [valuation, setValuation] = useState<ValuationResponse | null>(null);
  const [reports, setReports] = useState<AnalysisReport[]>([]);
  const [loading, setLoading] = useState(true);

  const [running, setRunning] = useState(false);
  const [pipelineMsg, setPipelineMsg] = useState<string | null>(null);
  const [dataRefreshKey, setDataRefreshKey] = useState(0);

  const [agentLayout, setAgentLayoutRaw] = useState<AgentLayout>(() => loadAgentLayout());
  const setAgentLayout = (v: AgentLayout) => {
    setAgentLayoutRaw(v);
    localStorage.setItem(AGENT_LAYOUT_KEY, v);
  };

  useEffect(() => {
    if (!ticker) return;
    loadAll();
  }, [ticker]);

  async function loadAll() {
    setLoading(true);
    try {
      const [stockData, scoreData, decisionData, valuationData, reportsData] = await Promise.all([
        api.stocks.get(ticker),
        api.scores.latest(ticker).catch(() => null),
        api.decision.latest(ticker).catch(() => null),
        api.stocks.valuation(ticker).catch(() => null),
        api.analysis.list(ticker).catch(() => []),
      ]);
      setStock(stockData);
      setScore(scoreData);
      setDecision(decisionData);
      setValuation(valuationData);
      setReports(reportsData);
    } catch {
      setStock(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleRunPipeline() {
    if (!ticker) return;
    try {
      setRunning(true);
      setPipelineMsg('Refreshing market data…');

      const ingestionResults = await api.ingestion.run([ticker]);
      const ingestion = ingestionResults.find((r) => r.ticker === ticker) ?? ingestionResults[0];
      const ingestionSummary = ingestion
        ? `${ingestion.prices} prices · ${ingestion.financials} financials · ${ingestion.news} news`
        : 'no ingestion result';
      setDataRefreshKey((v) => v + 1);

      setPipelineMsg(`Data refreshed (${ingestionSummary}). Running agents…`);

      const agentResult = await api.analysis.run(ticker, true);
      const agentSummary = agentResult.results
        .map((r) => `${r.agent_type}=${r.success ? 'ok' : 'failed'}`)
        .join(' · ');
      const agentFailures = agentResult.results.filter((r) => !r.success);
      if (agentFailures.length > 0) {
        const detail = agentFailures
          .map((r) => `${r.agent_type}${r.error ? `: ${r.error}` : ''}`)
          .join(' · ');
        throw new Error(`Agent refresh failed (${detail})`);
      }
      setPipelineMsg(`Agents done (${agentSummary}). Calculating score…`);

      const scoreResult = await api.scoring.run(ticker);
      setScore({
        ticker: scoreResult.ticker,
        date: scoreResult.date,
        growth_score: scoreResult.growth_score,
        profitability_score: scoreResult.profitability_score,
        valuation_score: scoreResult.valuation_score,
        momentum_score: scoreResult.momentum_score,
        sentiment_score: scoreResult.sentiment_score,
        risk_score: scoreResult.risk_score,
        event_score: scoreResult.event_score,
        composite_score: scoreResult.composite_score,
        signal: scoreResult.signal,
      });

      const decisionResult = await api.decision.run(ticker);
      setDecision(decisionResult);

      const reportsData = await api.analysis.list(ticker).catch(() => []);
      setReports(reportsData);
      const [stockData, valuationData] = await Promise.all([
        api.stocks.get(ticker).catch(() => null),
        api.stocks.valuation(ticker).catch(() => null),
      ]);
      if (stockData) setStock(stockData);
      setValuation(valuationData);

      setPipelineMsg(
        `Pipeline complete · ${scoreResult.feature_count} features · score ${scoreResult.composite_score.toFixed(
          3,
        )} · ${decisionResult.final_signal} (${decisionResult.confidence}, ${
          decisionResult.risk_flags.length
        } flag${decisionResult.risk_flags.length !== 1 ? 's' : ''})`,
      );
    } catch (err) {
      setPipelineMsg(err instanceof Error ? err.message : 'Pipeline failed');
    } finally {
      setRunning(false);
    }
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

      <PriceChart ticker={ticker} refreshKey={dataRefreshKey} />

      {decision && <DecisionPanel decision={decision} />}

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
