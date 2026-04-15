import type { Stock, StockScore } from '../api/client';

function formatPrice(price: number | null): string {
  if (price === null) return '—';
  return `$${price.toFixed(2)}`;
}

function formatChange(change: number | null): { text: string; color: string } {
  if (change === null) return { text: '—', color: 'text-gray-400' };
  const pct = (change * 100).toFixed(2);
  if (change > 0) return { text: `+${pct}%`, color: 'text-green-600' };
  if (change < 0) return { text: `${pct}%`, color: 'text-red-600' };
  return { text: '0.00%', color: 'text-gray-500' };
}

function signalStyle(signal: string): { bg: string; text: string } {
  switch (signal) {
    case 'STRONG_BUY': return { bg: 'bg-green-100', text: 'text-green-800' };
    case 'BUY': return { bg: 'bg-green-50', text: 'text-green-700' };
    case 'HOLD': return { bg: 'bg-gray-100', text: 'text-gray-700' };
    case 'REDUCE': return { bg: 'bg-orange-50', text: 'text-orange-700' };
    case 'SELL': return { bg: 'bg-red-100', text: 'text-red-800' };
    default: return { bg: 'bg-gray-100', text: 'text-gray-600' };
  }
}

function scoreColor(value: number): string {
  if (value >= 0.75) return 'text-green-600';
  if (value >= 0.6) return 'text-blue-600';
  if (value >= 0.45) return 'text-gray-600';
  if (value >= 0.3) return 'text-orange-600';
  return 'text-red-600';
}

export default function ScoreCard({ stock, score }: { stock: Stock; score?: StockScore | null }) {
  const change = formatChange(stock.price_change_pct);

  return (
    <div className="border border-gray-200 rounded-xl p-5 hover:shadow-md hover:border-gray-300 transition-all bg-white">
      <div className="flex justify-between items-start mb-3">
        <div>
          <div className="text-lg font-bold text-gray-900">{stock.ticker}</div>
          <div className="text-sm text-gray-500 truncate max-w-[160px]">{stock.name}</div>
        </div>
        {score ? (
          <span className={`text-xs font-bold px-2 py-0.5 rounded ${signalStyle(score.signal).bg} ${signalStyle(score.signal).text}`}>
            {score.signal.replace('_', ' ')}
          </span>
        ) : stock.sector ? (
          <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded">
            {stock.sector}
          </span>
        ) : null}
      </div>

      <div className="flex items-baseline gap-2 mb-3">
        <span className="text-2xl font-semibold text-gray-900">
          {formatPrice(stock.latest_price)}
        </span>
        <span className={`text-sm font-medium ${change.color}`}>{change.text}</span>
      </div>

      {score ? (
        <div className="flex items-center gap-2">
          <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
            <div
              className={`h-full rounded-full ${
                score.composite_score >= 0.75 ? 'bg-green-500' :
                score.composite_score >= 0.6 ? 'bg-blue-500' :
                score.composite_score >= 0.45 ? 'bg-gray-400' :
                score.composite_score >= 0.3 ? 'bg-orange-500' : 'bg-red-500'
              }`}
              style={{ width: `${score.composite_score * 100}%` }}
            />
          </div>
          <span className={`text-sm font-bold ${scoreColor(score.composite_score)}`}>
            {score.composite_score.toFixed(2)}
          </span>
        </div>
      ) : (
        <div className="text-xs text-gray-400">
          Run scoring to see composite score
        </div>
      )}
    </div>
  );
}
