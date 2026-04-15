import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import type { Stock, StockScore, AnalysisReport } from '../api/client';
import { api } from '../api/client';
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

export default function StockDetail() {
  const { ticker } = useParams<{ ticker: string }>();
  const [stock, setStock] = useState<Stock | null>(null);
  const [score, setScore] = useState<StockScore | null>(null);
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
      const [stockData, scoreData, reportsData] = await Promise.all([
        api.stocks.get(ticker!),
        api.scores.latest(ticker!).catch(() => null),
        api.analysis.list(ticker!).catch(() => []),
      ]);
      setStock(stockData);
      setScore(scoreData);
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
      const result = await api.scoring.run(ticker);
      setScore({
        ticker: result.ticker,
        date: result.date,
        growth_score: result.growth_score,
        profitability_score: result.profitability_score,
        valuation_score: result.valuation_score,
        momentum_score: result.momentum_score,
        sentiment_score: result.sentiment_score,
        risk_score: result.risk_score,
        event_score: result.event_score,
        composite_score: result.composite_score,
        signal: result.signal,
      });
      setScoreMessage(`Score calculated: ${result.composite_score.toFixed(3)} (${result.signal}) from ${result.feature_count} features`);
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

      {/* Score Breakdown */}
      <div className="mb-8">
        <div className="flex items-center gap-4 mb-4">
          <h2 className="text-xl font-semibold text-gray-800">Score Breakdown</h2>
          <button
            onClick={handleRunScoring}
            disabled={scoring}
            className="bg-blue-600 text-white px-3 py-1.5 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {scoring ? 'Calculating...' : score ? 'Recalculate Score' : 'Calculate Score'}
          </button>
        </div>

        {scoreMessage && (
          <div className="bg-blue-50 border border-blue-200 text-blue-700 px-4 py-2 rounded-lg mb-4 text-sm">
            {scoreMessage}
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
