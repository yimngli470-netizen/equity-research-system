import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import type { DailyPrice } from '../../api/client';
import Card from '../primitives/Card';

interface Props {
  ticker: string;
  refreshKey?: number;
}

const RANGES = [
  { label: '1M', days: 21 },
  { label: '3M', days: 63 },
  { label: '6M', days: 126 },
  { label: '1Y', days: 252 },
  { label: '5Y', days: 252 * 5 },
];

export default function PriceChart({ ticker, refreshKey = 0 }: Props) {
  const [prices, setPrices] = useState<DailyPrice[]>([]);
  const [rangeIdx, setRangeIdx] = useState(1); // 3M default
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.prices
      .get(ticker, 252 * 5)
      .then((data) => setPrices(data))
      .catch(() => setPrices([]))
      .finally(() => setLoading(false));
  }, [ticker, refreshKey]);

  const days = RANGES[rangeIdx].days;
  // Sort ascending and drop rows without a usable close (a bad/incomplete ingested bar serializes
  // close as null — one such row must not blank the chart, let alone the page).
  const sorted = [...prices]
    .filter((p) => p.close != null && Number.isFinite(p.close))
    .sort((a, b) => (a.date < b.date ? -1 : 1));
  const sliced = sorted.slice(-days);
  const points = sliced.map((p, i) => ({ day: i, price: p.close }));
  const latest = sorted.at(-1);

  const width = 880;
  const height = 200;

  return (
    <Card padding={20} style={{ marginBottom: 18 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <h3
          style={{
            fontSize: 13,
            letterSpacing: '.1em',
            textTransform: 'uppercase',
            color: 'var(--color-ink-3)',
            fontWeight: 600,
            margin: 0,
          }}
        >
          Price · {RANGES[rangeIdx].label}
        </h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {latest && (
            <div style={{ fontSize: 11, color: 'var(--color-ink-3)', fontFamily: 'var(--font-mono)' }}>
              {latest.date} · ${latest.close.toFixed(2)}
            </div>
          )}
          <div style={{ display: 'flex', gap: 6, fontSize: 11, color: 'var(--color-ink-3)' }}>
          {RANGES.map((r, i) => (
            <button
              key={r.label}
              onClick={() => setRangeIdx(i)}
              style={{
                padding: '2px 8px',
                borderRadius: 4,
                background: i === rangeIdx ? 'var(--color-surface-2)' : 'transparent',
                color: i === rangeIdx ? 'var(--color-ink)' : 'var(--color-ink-3)',
                cursor: 'pointer',
                border: 'none',
                fontFamily: 'var(--font-ui)',
                fontSize: 11,
              }}
            >
              {r.label}
            </button>
          ))}
          </div>
        </div>
      </div>
      {loading ? (
        <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-ink-3)' }}>
          Loading…
        </div>
      ) : points.length < 2 ? (
        <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-ink-3)' }}>
          Not enough price data
        </div>
      ) : (
        <PriceChartSVG points={points} width={width} height={height} />
      )}
    </Card>
  );
}

function PriceChartSVG({ points, width, height }: { points: { day: number; price: number }[]; width: number; height: number }) {
  const xs = points.map((p) => p.day);
  const ys = points.map((p) => p.price);
  const xmin = Math.min(...xs);
  const xmax = Math.max(...xs);
  const ymin = Math.min(...ys);
  const ymax = Math.max(...ys);
  const xrange = Math.max(xmax - xmin, 1e-6);
  const yrange = Math.max(ymax - ymin, 1e-6);
  const padX = 36;
  const padY = 28;
  const w = width - padX * 2;
  const h = height - padY * 2;
  const path = points
    .map((p, i) => {
      const x = padX + ((p.day - xmin) / xrange) * w;
      const y = padY + h - ((p.price - ymin) / yrange) * h;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  const areaPath = path + ` L${padX + w},${padY + h} L${padX},${padY + h} Z`;
  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => ymin + (yrange * i) / ticks);

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: 'block', fontFamily: 'var(--font-mono)' }}>
      <defs>
        <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--color-ink)" stopOpacity="0.08" />
          <stop offset="100%" stopColor="var(--color-ink)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {yTicks.map((t, i) => {
        const y = padY + h - ((t - ymin) / yrange) * h;
        return (
          <g key={i}>
            <line x1={padX} y1={y} x2={padX + w} y2={y} stroke="var(--color-rule-soft)" strokeWidth="1" />
            <text x={padX + w + 6} y={y + 3} fontSize="10" fill="var(--color-ink-3)">
              ${t.toFixed(0)}
            </text>
          </g>
        );
      })}
      <path d={areaPath} fill="url(#chartFill)" />
      <path d={path} fill="none" stroke="var(--color-ink)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
