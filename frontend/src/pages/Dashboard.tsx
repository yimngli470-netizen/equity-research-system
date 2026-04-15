import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Stock, StockScore } from '../api/client';
import { api } from '../api/client';
import ScoreCard from '../components/ScoreCard';

export default function Dashboard() {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [scores, setScores] = useState<Record<string, StockScore | null>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Add stock form
  const [ticker, setTicker] = useState('');
  const [name, setName] = useState('');
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    loadStocks();
  }, []);

  async function loadStocks() {
    try {
      setLoading(true);
      const data = await api.stocks.list();
      setStocks(data);

      // Fetch latest scores for each stock
      const scoreMap: Record<string, StockScore | null> = {};
      await Promise.all(
        data.map(async (s) => {
          try {
            scoreMap[s.ticker] = await api.scores.latest(s.ticker);
          } catch {
            scoreMap[s.ticker] = null;
          }
        })
      );
      setScores(scoreMap);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load stocks');
    } finally {
      setLoading(false);
    }
  }

  async function handleAddStock(e: React.FormEvent) {
    e.preventDefault();
    if (!ticker.trim() || !name.trim()) return;
    try {
      setAdding(true);
      await api.stocks.add({ ticker: ticker.trim().toUpperCase(), name: name.trim() });
      setTicker('');
      setName('');
      await loadStocks();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add stock');
    } finally {
      setAdding(false);
    }
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">AI Equity Research Dashboard</h1>
        <p className="text-gray-500 mt-1">Track, analyze, and score your portfolio</p>
      </div>

      {/* Add Stock Form */}
      <form onSubmit={handleAddStock} className="mb-8 flex gap-3 items-end">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Ticker</label>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="NVDA"
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-28 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Company Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="NVIDIA Corporation"
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <button
          type="submit"
          disabled={adding}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {adding ? 'Adding...' : 'Add Stock'}
        </button>
      </form>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-6">
          {error}
          <button onClick={() => setError(null)} className="ml-3 underline text-sm">Dismiss</button>
        </div>
      )}

      {/* Stock Grid */}
      {loading ? (
        <div className="text-gray-500">Loading stocks...</div>
      ) : stocks.length === 0 ? (
        <div className="text-gray-400 py-12">No stocks in your watchlist. Add one above to get started.</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {stocks.map((stock) => (
            <Link key={stock.ticker} to={`/stock/${stock.ticker}`} className="no-underline">
              <ScoreCard stock={stock} score={scores[stock.ticker]} />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
