import { useEffect, useState } from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import type { DailyPrice } from '../api/client';
import { api } from '../api/client';

type Range = '1M' | '3M' | '6M' | '1Y';

const RANGE_LIMITS: Record<Range, number> = {
  '1M': 22,
  '3M': 64,
  '6M': 126,
  '1Y': 252,
};

export default function PriceChart({ ticker }: { ticker: string }) {
  const [prices, setPrices] = useState<DailyPrice[]>([]);
  const [range, setRange] = useState<Range>('3M');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.prices
      .get(ticker, RANGE_LIMITS[range])
      .then((data) => {
        // API returns newest first, chart needs oldest first
        setPrices([...data].reverse());
      })
      .catch(() => setPrices([]))
      .finally(() => setLoading(false));
  }, [ticker, range]);

  if (loading) return <div className="text-gray-400 text-sm py-8">Loading chart...</div>;
  if (prices.length === 0) return <div className="text-gray-400 text-sm py-8">No price data available.</div>;

  const first = prices[0].close;
  const last = prices[prices.length - 1].close;
  const isPositive = last >= first;
  const color = isPositive ? '#16a34a' : '#dc2626';
  const fillColor = isPositive ? '#dcfce7' : '#fee2e2';

  const minPrice = Math.min(...prices.map((p) => p.low));
  const maxPrice = Math.max(...prices.map((p) => p.high));
  const padding = (maxPrice - minPrice) * 0.05;

  return (
    <div className="border border-gray-200 rounded-xl p-5 bg-white">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-700">Price History</h3>
        <div className="flex gap-1">
          {(['1M', '3M', '6M', '1Y'] as Range[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-2.5 py-1 text-xs rounded font-medium ${
                range === r
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={prices} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`gradient-${ticker}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={fillColor} stopOpacity={0.8} />
              <stop offset="100%" stopColor={fillColor} stopOpacity={0.1} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            tickFormatter={(d: string) => {
              const date = new Date(d + 'T00:00:00');
              return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            }}
            interval={Math.max(0, Math.floor(prices.length / 5) - 1)}
          />
          <YAxis
            domain={[minPrice - padding, maxPrice + padding]}
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            tickFormatter={(v: number) => `$${v.toFixed(0)}`}
            width={55}
          />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
            formatter={(value) => {
              const numericValue = typeof value === 'number' ? value : Number(value);
              return [`$${numericValue.toFixed(2)}`, 'Close'];
            }}
            labelFormatter={(label) => {
              const date = new Date(String(label) + 'T00:00:00');
              return date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
            }}
          />
          <Area
            type="monotone"
            dataKey="close"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#gradient-${ticker})`}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
