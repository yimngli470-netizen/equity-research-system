import type { StockScore } from '../api/client';

const CATEGORIES = [
  { key: 'growth_score', label: 'Growth' },
  { key: 'profitability_score', label: 'Profitability' },
  { key: 'valuation_score', label: 'Valuation' },
  { key: 'momentum_score', label: 'Momentum' },
  { key: 'sentiment_score', label: 'Sentiment' },
  { key: 'risk_score', label: 'Risk' },
  { key: 'event_score', label: 'Events' },
] as const;

function scoreColor(value: number): string {
  if (value >= 0.75) return 'bg-green-500';
  if (value >= 0.5) return 'bg-blue-500';
  if (value >= 0.25) return 'bg-yellow-500';
  return 'bg-red-500';
}

function signalBadge(signal: string): { bg: string; text: string } {
  switch (signal) {
    case 'STRONG_BUY': return { bg: 'bg-green-100 border-green-300', text: 'text-green-800' };
    case 'BUY': return { bg: 'bg-green-50 border-green-200', text: 'text-green-700' };
    case 'HOLD': return { bg: 'bg-gray-100 border-gray-300', text: 'text-gray-700' };
    case 'REDUCE': return { bg: 'bg-orange-50 border-orange-200', text: 'text-orange-700' };
    case 'SELL': return { bg: 'bg-red-100 border-red-300', text: 'text-red-800' };
    default: return { bg: 'bg-gray-100 border-gray-300', text: 'text-gray-700' };
  }
}

export default function ScoreBreakdown({ score }: { score: StockScore }) {
  const badge = signalBadge(score.signal);

  return (
    <div className="border border-gray-200 rounded-xl p-6 bg-white">
      {/* Signal + Composite */}
      <div className="flex items-center gap-4 mb-6">
        <span className={`px-3 py-1.5 rounded-lg border text-sm font-bold ${badge.bg} ${badge.text}`}>
          {score.signal.replace('_', ' ')}
        </span>
        <div>
          <span className="text-sm text-gray-500">Composite Score</span>
          <span className="ml-2 text-2xl font-bold text-gray-900">{score.composite_score.toFixed(2)}</span>
        </div>
      </div>

      {/* Score Bars */}
      <div className="space-y-3">
        {CATEGORIES.map(({ key, label }) => {
          const value = score[key];
          return (
            <div key={key} className="flex items-center gap-3">
              <span className="text-sm text-gray-600 w-28 text-right">{label}</span>
              <div className="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
                <div
                  className={`h-full rounded-full ${scoreColor(value)}`}
                  style={{ width: `${value * 100}%` }}
                />
              </div>
              <span className="text-sm font-mono text-gray-700 w-12">{value.toFixed(2)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
