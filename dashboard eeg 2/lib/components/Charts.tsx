'use client';
import { useState } from 'react';

export interface Series {
  name: string;
  values: number[];
  color: string;
  fill?: boolean;
  dashed?: boolean;
}

const W = 640, H = 260, PL = 44, PR = 16, PT = 16, PB = 30;
const GRID = '#26262b';

/** Stock-style line / area chart with a crosshair that follows the cursor. */
export function LineChart({
  labels, tips, series, yMin = 0, yMax, digits = 2, id,
}: {
  labels: string[]; tips: string[]; series: Series[]; yMin?: number; yMax: number; digits?: number; id: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = labels.length;
  const x = (i: number) => PL + (n === 1 ? (W - PL - PR) / 2 : (i * (W - PL - PR)) / (n - 1));
  const y = (v: number) => PT + (1 - (v - yMin) / (yMax - yMin)) * (H - PT - PB);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => yMin + t * (yMax - yMin));
  const line = (v: number[]) => v.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p)}`).join(' ');
  const area = (v: number[]) => `${line(v)} L${x(n - 1)},${y(yMin)} L${x(0)},${y(yMin)} Z`;

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((px - PL) / (W - PL - PR)) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  return (
    <div className="chart">
      <div className="legend">
        {series.map((s) => (
          <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id={`g-${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ff2a2a" stopOpacity=".45" />
            <stop offset="100%" stopColor="#ff2a2a" stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PL} x2={W - PR} y1={y(t)} y2={y(t)} stroke={GRID} />
            <text x={PL - 8} y={y(t) + 4} textAnchor="end" fontSize="10" fill="#6b6e75" fontFamily="monospace">
              {t.toFixed(digits)}
            </text>
          </g>
        ))}
        {labels.map((l, i) => (
          <text key={l} x={x(i)} y={H - 10} textAnchor="middle" fontSize="10" fill="#6b6e75" fontFamily="monospace">{l}</text>
        ))}
        {series.map((s) => (
          <g key={s.name}>
            {s.fill && <path d={area(s.values)} fill={`url(#g-${id})`} />}
            <path d={line(s.values)} fill="none" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? '5 4' : undefined} />
          </g>
        ))}
        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PT} y2={H - PB} stroke="#ff2a2a" strokeDasharray="3 3" opacity=".7" />
            {series.map((s) => (
              <circle key={s.name} cx={x(hover)} cy={y(s.values[hover])} r="4" fill="#000" stroke={s.color} strokeWidth="2" />
            ))}
          </g>
        )}
      </svg>
      {hover !== null && (
        <div className="tip" style={{ left: `${(x(hover) / W) * 100}%` }}>
          <div style={{ color: '#a7aab0', marginBottom: 3 }}>{tips[hover]}</div>
          {series.map((s) => (
            <div key={s.name}>{s.name}: <span className="red">{s.values[hover].toFixed(Math.max(digits, 2))}</span></div>
          ))}
        </div>
      )}
    </div>
  );
}

export interface BarRow { label: string; raw: number; cleaned: number; total: number }

/** Horizontal bar chart: grey = raw, red = cleaned. Hover a bar for the count. */
export function PassBars({ rows }: { rows: BarRow[] }) {
  const [tip, setTip] = useState('');
  return (
    <div>
      <div className="legend">
        <span><i style={{ background: '#6b6e75' }} />raw</span>
        <span><i style={{ background: '#ff2a2a' }} />cleaned</span>
        <span className="red" style={{ marginLeft: 'auto' }}>{tip}</span>
      </div>
      {rows.map((r) => (
        <div className="barrow" key={r.label}>
          <div className="name">{r.label}</div>
          <div>
            {([['raw', r.raw, '#6b6e75'], ['cleaned', r.cleaned, '#ff2a2a']] as const).map(([k, v, c]) => (
              <div className="bar" key={k}>
                <div className="track">
                  <div
                    className="fill"
                    style={{ width: `${(v / r.total) * 100}%`, background: c }}
                    onMouseEnter={() => setTip(`${r.label} · ${k}: ${v} of ${r.total} files passed`)}
                    onMouseLeave={() => setTip('')}
                  />
                </div>
                <span className="val">{v}/{r.total}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
