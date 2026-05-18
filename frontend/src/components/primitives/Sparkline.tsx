interface Props {
  data: number[];
  width?: number;
  height?: number;
  stroke?: string;
}

export default function Sparkline({ data, width = 80, height = 24, stroke = 'currentColor' }: Props) {
  if (!data || data.length === 0) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = Math.max(max - min, 1e-6);
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
  return (
    <svg width={width} height={height} style={{ display: 'block', overflow: 'visible' }}>
      <polyline
        fill="none"
        stroke={stroke}
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}

// Deterministic 24-point sparkline from a ticker. Used as a placeholder
// until real prices are wired in for the dashboard.
export function genSparkSeed(ticker: string): number[] {
  let h = 0;
  for (const c of ticker) h = (h * 31 + c.charCodeAt(0)) % 1000;
  const data: number[] = [];
  let v = 50 + (h % 30);
  for (let i = 0; i < 24; i++) {
    h = (h * 1103515245 + 12345) & 0x7fffffff;
    v += ((h % 100) - 50) / 8;
    data.push(v);
  }
  return data;
}
