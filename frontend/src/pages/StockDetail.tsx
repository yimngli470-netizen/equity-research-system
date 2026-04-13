import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import type { Stock, StockScore, AnalysisReport } from '../api/client';
import { api } from '../api/client';
import ScoreBreakdown from '../components/ScoreBreakdown';

export default function StockDetail() {
  const { ticker } = useParams<{ ticker: string }>();
  const [stock, setStock] = useState<Stock | null>(null);
  const [score, setScore] = useState<StockScore | null>(null);
  const [reports, setReports] = useState<AnalysisReport[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ticker) return;
    async function load() {
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
    load();
  }, [ticker]);

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
      {score ? (
        <div className="mb-8">
          <h2 className="text-xl font-semibold text-gray-800 mb-4">Score Breakdown</h2>
          <ScoreBreakdown score={score} />
        </div>
      ) : (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 mb-8 text-gray-500">
          No scores yet. Run the analysis pipeline to generate scores.
        </div>
      )}

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
              <div key={report.id} className="border border-gray-200 rounded-lg p-4">
                <div className="flex justify-between items-center mb-2">
                  <span className="font-medium text-gray-800 capitalize">{report.agent_type} Analysis</span>
                  <span className="text-sm text-gray-500">{report.run_date}</span>
                </div>
                <pre className="text-xs bg-gray-50 p-3 rounded overflow-x-auto">
                  {JSON.stringify(report.report, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
