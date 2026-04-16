import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import type { Stock, StockScore, AnalysisReport, Decision, RiskFlag } from '../api/client';
import { api } from '../api/client';
import FinancialsTable from '../components/FinancialsTable';
import PriceChart from '../components/PriceChart';
import ScoreBreakdown from '../components/ScoreBreakdown';

function AgentReportCard({ report }: { report: AnalysisReport }) {
  const [expanded, setExpanded] = useState(false);
  const data = report.report as Record<string, unknown>;

  const summary = (data.summary as string) || null;
  const signal = (data.signal as string) || (data.valuation_verdict as string) || null;

  return (
    <div className="border border-gray-200 rounded-lg p-4 bg-white">
      <div className="flex justify-between items-center mb-2">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-gray-800 capitalize">{report.agent_type} Analysis</span>
          {signal && (
            <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded font-medium">
              {String(signal).replace(/_/g, ' ')}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-400">v{report.version}</span>
          <span className="text-sm text-gray-500">{report.run_date}</span>
        </div>
      </div>

      {summary && (
        <p className="text-sm text-gray-600 mb-3 leading-relaxed">{summary}</p>
      )}

      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-blue-600 hover:underline"
      >
        {expanded ? 'Hide raw data' : 'Show raw data'}
      </button>

      {expanded && (
        <pre className="text-xs bg-gray-50 p-3 rounded overflow-x-auto mt-2 max-h-96 overflow-y-auto">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}

function flagLevelStyle(level: string): { border: string; bg: string; text: string; dot: string } {
  switch (level) {
    case 'critical': return { border: 'border-red-300', bg: 'bg-red-50', text: 'text-red-800', dot: 'bg-red-500' };
    case 'major': return { border: 'border-orange-300', bg: 'bg-orange-50', text: 'text-orange-800', dot: 'bg-orange-500' };
    case 'watch': return { border: 'border-yellow-300', bg: 'bg-yellow-50', text: 'text-yellow-800', dot: 'bg-yellow-500' };
    default: return { border: 'border-gray-300', bg: 'bg-gray-50', text: 'text-gray-800', dot: 'bg-gray-500' };
  }
}

function confidenceStyle(confidence: string): string {
  switch (confidence) {
    case 'high': return 'text-green-700 bg-green-50 border-green-200';
    case 'moderate': return 'text-yellow-700 bg-yellow-50 border-yellow-200';
    case 'low': return 'text-red-700 bg-red-50 border-red-200';
    default: return 'text-gray-700 bg-gray-50 border-gray-200';
  }
}

function DecisionPanel({ decision }: { decision: Decision }) {
  const signalChanged = decision.raw_signal !== decision.final_signal;

  return (
    <div className="border border-gray-200 rounded-xl p-6 bg-white">
      {/* Final Signal + Confidence */}
      <div className="flex items-center gap-4 mb-4">
        <div className="flex items-center gap-3">
          <span className={`px-3 py-1.5 rounded-lg border text-sm font-bold ${
            decision.final_signal === 'STRONG_BUY' ? 'bg-green-100 border-green-300 text-green-800' :
            decision.final_signal === 'BUY' ? 'bg-green-50 border-green-200 text-green-700' :
            decision.final_signal === 'HOLD' ? 'bg-gray-100 border-gray-300 text-gray-700' :
            decision.final_signal === 'REDUCE' ? 'bg-orange-50 border-orange-200 text-orange-700' :
            'bg-red-100 border-red-300 text-red-800'
          }`}>
            {decision.final_signal.replace('_', ' ')}
          </span>
          {signalChanged && (
            <span className="text-sm text-gray-400">
              (was {decision.raw_signal.replace('_', ' ')})
            </span>
          )}
        </div>
        <span className={`text-xs font-medium px-2 py-1 rounded border ${confidenceStyle(decision.confidence)}`}>
          {decision.confidence} confidence
        </span>
      </div>

      {/* Reasoning */}
      <p className="text-sm text-gray-600 mb-4 leading-relaxed">{decision.reasoning}</p>

      {/* Risk Flags */}
      {decision.risk_flags.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Risk Flags ({decision.risk_flags.length})</h3>
          <div className="space-y-2">
            {decision.risk_flags.map((flag: RiskFlag, i: number) => {
              const style = flagLevelStyle(flag.level);
              return (
                <div key={i} className={`flex items-start gap-2 border rounded-lg px-3 py-2 ${style.border} ${style.bg}`}>
                  <span className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${style.dot}`} />
                  <div>
                    <span className={`text-xs font-bold uppercase ${style.text}`}>{flag.level}</span>
                    <span className="text-xs text-gray-500 ml-2">{flag.category}</span>
                    <p className={`text-sm ${style.text}`}>{flag.message}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {decision.risk_flags.length === 0 && (
        <div className="text-sm text-green-600 bg-green-50 border border-green-200 rounded-lg px-3 py-2">
          No risk flags triggered — clean signal.
        </div>
      )}
    </div>
  );
}

export default function StockDetail() {
  const { ticker } = useParams<{ ticker: string }>();
  const [stock, setStock] = useState<Stock | null>(null);
  const [score, setScore] = useState<StockScore | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [reports, setReports] = useState<AnalysisReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [scoring, setScoring] = useState(false);
  const [scoreMessage, setScoreMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker) return;
    loadData();
  }, [ticker]);

  async function loadData() {
    setLoading(true);
    try {
      const [stockData, scoreData, decisionData, reportsData] = await Promise.all([
        api.stocks.get(ticker!),
        api.scores.latest(ticker!).catch(() => null),
        api.decision.latest(ticker!).catch(() => null),
        api.analysis.list(ticker!).catch(() => []),
      ]);
      setStock(stockData);
      setScore(scoreData);
      setDecision(decisionData);
      setReports(reportsData);
    } catch {
      // stock not found handled by null state
    } finally {
      setLoading(false);
    }
  }

  async function handleRunScoring() {
    if (!ticker) return;
    try {
      setScoring(true);
      setScoreMessage(null);
      // Run scoring first
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
      // Then run decision engine
      const decisionResult = await api.decision.run(ticker);
      setDecision(decisionResult);
      setScoreMessage(
        `Score: ${scoreResult.composite_score.toFixed(3)} | Decision: ${decisionResult.final_signal} (${decisionResult.confidence} confidence, ${decisionResult.risk_flags.length} flags)`
      );
    } catch (err) {
      setScoreMessage(err instanceof Error ? err.message : 'Scoring failed');
    } finally {
      setScoring(false);
    }
  }

  if (loading) return <div className="text-gray-500">Loading...</div>;
  if (!stock) return <div className="text-red-500">Stock {ticker} not found.</div>;

  return (
    <div>
      <Link to="/" className="text-blue-600 hover:underline text-sm mb-4 inline-block">
        &larr; Back to Dashboard
      </Link>

      <div className="flex items-baseline gap-4 mb-6">
        <h1 className="text-3xl font-bold text-gray-900">{stock.ticker}</h1>
        <span className="text-xl text-gray-500">{stock.name}</span>
        {stock.sector && (
          <span className="text-sm bg-gray-100 text-gray-600 px-2 py-1 rounded">{stock.sector}</span>
        )}
      </div>

      {/* Price Chart */}
      <div className="mb-8">
        <PriceChart ticker={stock.ticker} />
      </div>

      {/* Quarterly Financials */}
      <div className="mb-8">
        <FinancialsTable ticker={stock.ticker} />
      </div>

      {/* Decision + Score Section */}
      <div className="mb-8">
        <div className="flex items-center gap-4 mb-4">
          <h2 className="text-xl font-semibold text-gray-800">Decision & Score</h2>
          <button
            onClick={handleRunScoring}
            disabled={scoring}
            className="bg-blue-600 text-white px-3 py-1.5 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {scoring ? 'Calculating...' : score ? 'Recalculate' : 'Calculate Score'}
          </button>
        </div>

        {scoreMessage && (
          <div className="bg-blue-50 border border-blue-200 text-blue-700 px-4 py-2 rounded-lg mb-4 text-sm">
            {scoreMessage}
          </div>
        )}

        {decision && (
          <div className="mb-4">
            <DecisionPanel decision={decision} />
          </div>
        )}

        {score ? (
          <ScoreBreakdown score={score} />
        ) : (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-gray-500">
            No scores yet. Click "Calculate Score" after running the analysis agents.
          </div>
        )}
      </div>

      {/* Analysis Reports */}
      <div>
        <h2 className="text-xl font-semibold text-gray-800 mb-4">Analysis Reports</h2>
        {reports.length === 0 ? (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-gray-500">
            No analysis reports yet. Reports will appear after the AI agents run.
          </div>
        ) : (
          <div className="space-y-4">
            {reports.map((report) => (
              <AgentReportCard key={report.id} report={report} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
