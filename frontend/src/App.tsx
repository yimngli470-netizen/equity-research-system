import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import StockDetail from './pages/StockDetail';

function BrandMark() {
  return (
    <div
      style={{
        width: 22,
        height: 22,
        border: '1.5px solid var(--color-ink)',
        borderRadius: 4,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 0,
          bottom: 0,
          width: '100%',
          height: '50%',
          background: 'var(--color-ink)',
        }}
      />
    </div>
  );
}

function TopBar() {
  const location = useLocation();
  const onCoverage = location.pathname === '/';
  const tickerMatch = location.pathname.match(/^\/stock\/([^/]+)/);
  const ticker = tickerMatch ? tickerMatch[1] : null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingBottom: 20,
        marginBottom: 28,
        borderBottom: '1px solid var(--color-rule)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <BrandMark />
        <Link
          to="/"
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: 'var(--color-ink)',
            textDecoration: 'none',
            letterSpacing: '-.005em',
          }}
        >
          Equity Research
        </Link>
      </div>
      <nav style={{ display: 'flex', alignItems: 'center', gap: 24, fontSize: 12 }}>
        <Link
          to="/"
          style={{
            color: onCoverage ? 'var(--color-ink)' : 'var(--color-ink-2)',
            fontWeight: onCoverage ? 500 : 400,
            textDecoration: 'none',
          }}
        >
          Coverage
        </Link>
        {ticker && (
          <Link
            to={`/stock/${ticker}`}
            style={{
              color: !onCoverage ? 'var(--color-ink)' : 'var(--color-ink-2)',
              fontWeight: !onCoverage ? 500 : 400,
              textDecoration: 'none',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {ticker}
          </Link>
        )}
        <span style={{ color: 'var(--color-ink-3)', cursor: 'not-allowed' }}>Compare</span>
        <span style={{ color: 'var(--color-ink-3)', cursor: 'not-allowed' }}>Settings</span>
      </nav>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div style={{ minHeight: '100vh', background: 'var(--color-bg)' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '32px 40px 80px' }}>
          <TopBar />
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/stock/:ticker" element={<StockDetail />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
