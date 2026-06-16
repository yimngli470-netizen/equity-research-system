import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import StockDetail from './pages/StockDetail';
import TrackRecord from './pages/TrackRecord';
import Universe from './pages/Universe';

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

function ThemeToggle({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 28,
        height: 28,
        marginLeft: 4,
        padding: 0,
        background: 'transparent',
        border: '1px solid var(--color-rule)',
        borderRadius: 6,
        color: 'var(--color-ink-2)',
        cursor: 'pointer',
        transition: 'all .15s ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.color = 'var(--color-ink)';
        e.currentTarget.style.borderColor = 'var(--color-ink-3)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.color = 'var(--color-ink-2)';
        e.currentTarget.style.borderColor = 'var(--color-rule)';
      }}
    >
      {dark ? (
        /* sun */
        <svg
          width="14"
          height="14"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        >
          <circle cx="8" cy="8" r="3" />
          <line x1="8" y1="1.5" x2="8" y2="3" />
          <line x1="8" y1="13" x2="8" y2="14.5" />
          <line x1="1.5" y1="8" x2="3" y2="8" />
          <line x1="13" y1="8" x2="14.5" y2="8" />
          <line x1="3.4" y1="3.4" x2="4.5" y2="4.5" />
          <line x1="11.5" y1="11.5" x2="12.6" y2="12.6" />
          <line x1="3.4" y1="12.6" x2="4.5" y2="11.5" />
          <line x1="11.5" y1="4.5" x2="12.6" y2="3.4" />
        </svg>
      ) : (
        /* moon */
        <svg
          width="14"
          height="14"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M13.5 9.5A6 6 0 0 1 6.5 2.5a6 6 0 1 0 7 7Z" />
        </svg>
      )}
    </button>
  );
}

function useTheme(): { dark: boolean; toggle: () => void } {
  // Read once on mount: localStorage > prefers-color-scheme > light
  const [dark, setDark] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    const stored = window.localStorage.getItem('theme');
    if (stored === 'dark') return true;
    if (stored === 'light') return false;
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  });

  useEffect(() => {
    const root = document.documentElement;
    if (dark) root.classList.add('dark');
    else root.classList.remove('dark');
    window.localStorage.setItem('theme', dark ? 'dark' : 'light');
  }, [dark]);

  return { dark, toggle: () => setDark((d) => !d) };
}

function TopBar({ dark, toggleTheme }: { dark: boolean; toggleTheme: () => void }) {
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
        <Link
          to="/universe"
          style={{
            color: location.pathname === '/universe' ? 'var(--color-ink)' : 'var(--color-ink-2)',
            fontWeight: location.pathname === '/universe' ? 500 : 400,
            textDecoration: 'none',
          }}
        >
          Universe
        </Link>
        <Link
          to="/track-record"
          style={{
            color: location.pathname === '/track-record' ? 'var(--color-ink)' : 'var(--color-ink-2)',
            fontWeight: location.pathname === '/track-record' ? 500 : 400,
            textDecoration: 'none',
          }}
        >
          Track Record
        </Link>
        <span style={{ color: 'var(--color-ink-3)', cursor: 'not-allowed' }}>Settings</span>
        <ThemeToggle dark={dark} onToggle={toggleTheme} />
      </nav>
    </div>
  );
}

export default function App() {
  const { dark, toggle } = useTheme();
  return (
    <BrowserRouter>
      <div style={{ minHeight: '100vh', background: 'var(--color-bg)' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '32px 40px 80px' }}>
          <TopBar dark={dark} toggleTheme={toggle} />
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/stock/:ticker" element={<StockDetail />} />
            <Route path="/universe" element={<Universe />} />
            <Route path="/track-record" element={<TrackRecord />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
