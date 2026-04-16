import { useEffect, useState } from 'react';
import { api } from '../api/client';

interface Financial {
  ticker: string;
  period: string;
  period_end_date: string;
  revenue: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  net_income: number | null;
  eps: number | null;
  free_cash_flow: number | null;
  operating_cash_flow: number | null;
  total_debt: number | null;
  cash_and_equivalents: number | null;
  total_assets: number | null;
  total_equity: number | null;
  shares_outstanding: number | null;
}

function fmt(val: number | null, divisor = 1e9, suffix = 'B'): string {
  if (val === null) return '—';
  return `$${(val / divisor).toFixed(2)}${suffix}`;
}

function fmtPct(val: number | null): string {
  if (val === null) return '—';
  return `${(val * 100).toFixed(1)}%`;
}

function margin(part: number | null, whole: number | null): number | null {
  if (part === null || whole === null || whole === 0) return null;
  return part / whole;
}

function growth(current: number | null, prior: number | null): number | null {
  if (current === null || prior === null || prior === 0) return null;
  return (current - prior) / Math.abs(prior);
}

function GrowthCell({ value }: { value: number | null }) {
  if (value === null) return <td className="px-3 py-2 text-right text-gray-400">—</td>;
  const pct = (value * 100).toFixed(1);
  const color = value > 0 ? 'text-green-600' : value < 0 ? 'text-red-600' : 'text-gray-600';
  return (
    <td className={`px-3 py-2 text-right text-xs font-medium ${color}`}>
      {value > 0 ? '+' : ''}{pct}%
    </td>
  );
}

export default function FinancialsTable({ ticker }: { ticker: string }) {
  const [financials, setFinancials] = useState<Financial[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/stocks/${ticker}/financials?limit=8`)
      .then((r) => r.json())
      .then((data) => setFinancials(data))
      .catch(() => setFinancials([]))
      .finally(() => setLoading(false));
  }, [ticker]);

  if (loading) return <div className="text-gray-400 text-sm py-4">Loading financials...</div>;
  if (financials.length === 0) return <div className="text-gray-400 text-sm py-4">No financial data available.</div>;

  // Compute YoY growth by matching same quarter from prior year
  const getYoYGrowth = (idx: number, field: keyof Financial): number | null => {
    // idx+4 would be same quarter last year (4 quarters back)
    if (idx + 4 >= financials.length) return null;
    return growth(
      financials[idx][field] as number | null,
      financials[idx + 4][field] as number | null
    );
  };

  return (
    <div className="border border-gray-200 rounded-xl bg-white overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-700">Quarterly Financials</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-gray-50 text-gray-500">
              <th className="px-3 py-2 text-left font-medium">Quarter</th>
              {financials.map((f) => (
                <th key={f.period} className="px-3 py-2 text-right font-medium whitespace-nowrap">
                  {f.period}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            <tr>
              <td className="px-3 py-2 text-gray-700 font-medium">Revenue</td>
              {financials.map((f) => (
                <td key={f.period} className="px-3 py-2 text-right text-gray-800">{fmt(f.revenue)}</td>
              ))}
            </tr>
            <tr className="bg-gray-50/50">
              <td className="px-3 py-2 text-gray-500 pl-5">Rev YoY</td>
              {financials.map((f, i) => (
                <GrowthCell key={f.period} value={getYoYGrowth(i, 'revenue')} />
              ))}
            </tr>
            <tr>
              <td className="px-3 py-2 text-gray-700 font-medium">Gross Profit</td>
              {financials.map((f) => (
                <td key={f.period} className="px-3 py-2 text-right text-gray-800">{fmt(f.gross_profit)}</td>
              ))}
            </tr>
            <tr className="bg-gray-50/50">
              <td className="px-3 py-2 text-gray-500 pl-5">Gross Margin</td>
              {financials.map((f) => (
                <td key={f.period} className="px-3 py-2 text-right text-gray-600">
                  {fmtPct(margin(f.gross_profit, f.revenue))}
                </td>
              ))}
            </tr>
            <tr>
              <td className="px-3 py-2 text-gray-700 font-medium">Operating Income</td>
              {financials.map((f) => (
                <td key={f.period} className="px-3 py-2 text-right text-gray-800">{fmt(f.operating_income)}</td>
              ))}
            </tr>
            <tr className="bg-gray-50/50">
              <td className="px-3 py-2 text-gray-500 pl-5">Op Margin</td>
              {financials.map((f) => (
                <td key={f.period} className="px-3 py-2 text-right text-gray-600">
                  {fmtPct(margin(f.operating_income, f.revenue))}
                </td>
              ))}
            </tr>
            <tr>
              <td className="px-3 py-2 text-gray-700 font-medium">Net Income</td>
              {financials.map((f) => (
                <td key={f.period} className="px-3 py-2 text-right text-gray-800">{fmt(f.net_income)}</td>
              ))}
            </tr>
            <tr className="bg-gray-50/50">
              <td className="px-3 py-2 text-gray-500 pl-5">Profit Margin</td>
              {financials.map((f) => (
                <td key={f.period} className="px-3 py-2 text-right text-gray-600">
                  {fmtPct(margin(f.net_income, f.revenue))}
                </td>
              ))}
            </tr>
            <tr>
              <td className="px-3 py-2 text-gray-700 font-medium">EPS</td>
              {financials.map((f) => (
                <td key={f.period} className="px-3 py-2 text-right text-gray-800">
                  {f.eps !== null ? `$${f.eps.toFixed(2)}` : '—'}
                </td>
              ))}
            </tr>
            <tr className="bg-gray-50/50">
              <td className="px-3 py-2 text-gray-500 pl-5">EPS YoY</td>
              {financials.map((f, i) => (
                <GrowthCell key={f.period} value={getYoYGrowth(i, 'eps')} />
              ))}
            </tr>
            <tr>
              <td className="px-3 py-2 text-gray-700 font-medium">Free Cash Flow</td>
              {financials.map((f) => (
                <td key={f.period} className="px-3 py-2 text-right text-gray-800">{fmt(f.free_cash_flow)}</td>
              ))}
            </tr>
            <tr className="bg-gray-50/50">
              <td className="px-3 py-2 text-gray-500 pl-5">FCF Margin</td>
              {financials.map((f) => (
                <td key={f.period} className="px-3 py-2 text-right text-gray-600">
                  {fmtPct(margin(f.free_cash_flow, f.revenue))}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
