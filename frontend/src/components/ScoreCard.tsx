import type { Stock } from '../api/client';

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

export default function ScoreCard({ stock }: { stock: Stock }) {
  const change = formatChange(stock.price_change_pct);

  return (
    <div className="border border-gray-200 rounded-xl p-5 hover:shadow-md hover:border-gray-300 transition-all bg-white">
      <div className="flex justify-between items-start mb-3">
        <div>
          <div className="text-lg font-bold text-gray-900">{stock.ticker}</div>
          <div className="text-sm text-gray-500 truncate max-w-[160px]">{stock.name}</div>
        </div>
        {stock.sector && (
          <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded">
            {stock.sector}
          </span>
        )}
      </div>

      <div className="flex items-baseline gap-2 mb-3">
        <span className="text-2xl font-semibold text-gray-900">
          {formatPrice(stock.latest_price)}
        </span>
        <span className={`text-sm font-medium ${change.color}`}>{change.text}</span>
      </div>

      <div className="text-xs text-gray-400">
        Score and signal will appear after analysis
      </div>
    </div>
  );
}
