"use client";

/** 대시보드 차트 — 라이브러리 없이 SVG(토스 톤: 얇은 선, 옅은 눈금, 값 글자 최소). */
import { useMemo, useRef, useState } from "react";

export const PALETTE = ["#3182f6", "#1F3A5F", "#7A9CC6", "#0f9d8a", "#8b5cf6"];

export function Sparkline({ values, width = 120, height = 32, className, color = "#3182f6" }: { values: number[]; width?: number; height?: number; className?: string; color?: string }) {
  const d = useMemo(() => {
    const v = values.filter((x) => Number.isFinite(x));
    if (v.length < 2) return "";
    const lo = Math.min(...v);
    const hi = Math.max(...v);
    const span = hi - lo || 1;
    return v.map((x, i) => `${i === 0 ? "M" : "L"}${((i / (v.length - 1)) * width).toFixed(1)},${(height - 2 - ((x - lo) / span) * (height - 4)).toFixed(1)}`).join(" ");
  }, [values, width, height]);
  if (!d) return <svg width={width} height={height} className={className} aria-hidden />;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={className} aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function niceTicks(lo: number, hi: number, n = 4): number[] {
  const span = hi - lo || Math.abs(hi) || 1;
  const step = 10 ** Math.floor(Math.log10(span / n));
  const mult = [1, 2, 2.5, 5, 10].find((m) => span / (step * m) <= n) ?? 10;
  const s = step * mult;
  const out: number[] = [];
  for (let t = Math.ceil(lo / s) * s; t <= hi + 1e-9; t += s) out.push(Number(t.toFixed(10)));
  return out;
}

export interface LineSeries {
  name: string;
  points: { date: string; value: number }[];
  decimals?: number;
  unit?: string;
}

/** 여러 선 — 날짜 축 공유. 마우스를 올리면 그 날짜의 값들. */
export function LineChart({ series, height = 220 }: { series: LineSeries[]; height?: number }) {
  const W = 640;
  const H = height;
  const pad = { l: 44, r: 12, t: 10, b: 24 };
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const dates = useMemo(() => [...new Set(series.flatMap((s) => s.points.map((p) => p.date)))].sort(), [series]);
  const vals = series.flatMap((s) => s.points.map((p) => p.value));
  if (!dates.length || !vals.length) return <p className="py-10 text-center text-[13px] text-text-secondary">값이 없습니다.</p>;
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const padV = (hi - lo || Math.abs(hi) || 1) * 0.08;
  const y0 = lo - padV;
  const y1 = hi + padV;
  const x = (i: number) => pad.l + (dates.length === 1 ? 0 : (i / (dates.length - 1)) * (W - pad.l - pad.r));
  const y = (v: number) => pad.t + (1 - (v - y0) / (y1 - y0)) * (H - pad.t - pad.b);
  const idx = new Map(dates.map((d, i) => [d, i]));
  const ticks = niceTicks(y0, y1);
  const dec = series[0]?.decimals ?? 2;
  const xl = [0, Math.floor((dates.length - 1) / 2), dates.length - 1];

  const move = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((px - pad.l) / (W - pad.l - pad.r)) * (dates.length - 1));
    setHover(Math.max(0, Math.min(dates.length - 1, i)));
  };

  return (
    <div className="relative">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="w-full" onMouseMove={move} onMouseLeave={() => setHover(null)} role="img" aria-label={series.map((s) => s.name).join(", ")}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="#eef0f3" />
            <text x={pad.l - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill="#8b95a1" className="num">
              {t.toLocaleString("ko-KR", { maximumFractionDigits: Math.max(0, dec) })}
            </text>
          </g>
        ))}
        {xl.map((i) => (
          <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? "start" : i === dates.length - 1 ? "end" : "middle"} fontSize={10} fill="#8b95a1">
            {dates[i]}
          </text>
        ))}
        {series.map((s, k) => (
          <path
            key={s.name}
            d={s.points.map((p, j) => `${j === 0 ? "M" : "L"}${x(idx.get(p.date) ?? 0).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ")}
            fill="none"
            stroke={PALETTE[k % PALETTE.length]}
            strokeWidth={1.8}
            strokeLinejoin="round"
          />
        ))}
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={H - pad.b} stroke="#d1d6db" />}
      </svg>
      {hover != null && (
        <div className="pointer-events-none absolute top-1 right-2 rounded-lg bg-white/95 px-2.5 py-1.5 text-[11px] shadow ring-1 ring-black/5">
          <div className="font-semibold text-text-primary">{dates[hover]}</div>
          {series.map((s, k) => {
            const p = s.points.find((q) => q.date === dates[hover]);
            return (
              p && (
                <div key={s.name} className="num flex items-center gap-1.5">
                  <span className="size-2 rounded-full" style={{ background: PALETTE[k % PALETTE.length] }} />
                  {s.name} {p.value.toLocaleString("ko-KR", { maximumFractionDigits: s.decimals ?? 2 })}
                  {s.unit && ` ${s.unit}`}
                </div>
              )
            );
          })}
        </div>
      )}
      {series.length > 1 && (
        <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-text-secondary">
          {series.map((s, k) => (
            <span key={s.name} className="flex items-center gap-1">
              <span className="size-2 rounded-full" style={{ background: PALETTE[k % PALETTE.length] }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export interface BarSeries {
  name: string;
  values: (number | null)[];
}

/** 묶음 막대 — 범주마다 계열을 나란히(음수는 0 선 아래로). 막대를 누르면 onPick(계열, 범주). */
export function GroupedBars({ categories, series, height = 220, decimals = 1, onPick }: { categories: string[]; series: BarSeries[]; height?: number; decimals?: number; onPick?: (s: number, c: number) => void }) {
  const W = 640;
  const H = height;
  const pad = { l: 44, r: 8, t: 16, b: 24 };
  const vals = series.flatMap((s) => s.values).filter((v): v is number => v != null);
  if (!categories.length || !vals.length) return <p className="py-10 text-center text-[13px] text-text-secondary">값이 없습니다.</p>;
  const lo = Math.min(0, ...vals);
  const hi = Math.max(0, ...vals);
  const y0 = lo - (hi - lo) * (lo < 0 ? 0.08 : 0);
  const y1 = hi + (hi - lo || 1) * 0.1;
  const y = (v: number) => pad.t + (1 - (v - y0) / (y1 - y0)) * (H - pad.t - pad.b);
  const gw = (W - pad.l - pad.r) / categories.length;
  const bw = Math.min(26, (gw * 0.72) / series.length);
  const fmt = (v: number) => v.toLocaleString("ko-KR", { maximumFractionDigits: decimals, minimumFractionDigits: Math.abs(v) < 100 ? decimals : 0 });
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={series.map((s) => s.name).join(", ")}>
        {niceTicks(y0, y1).map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke={t === 0 ? "#d1d6db" : "#eef0f3"} />
            <text x={pad.l - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill="#8b95a1" className="num">
              {t.toLocaleString("ko-KR")}
            </text>
          </g>
        ))}
        {categories.map((c, i) => {
          const gx = pad.l + i * gw + (gw - bw * series.length - 3 * (series.length - 1)) / 2;
          return (
            <g key={c}>
              {series.map((s, k) => {
                const v = s.values[i];
                if (v == null) return null;
                const top = Math.min(y(v), y(0));
                const h = Math.max(1, Math.abs(y(v) - y(0)));
                const x = gx + k * (bw + 3);
                return (
                  <g key={s.name} onClick={onPick ? () => onPick(k, i) : undefined} className={onPick ? "cursor-pointer" : undefined}>
                    <title>{`${s.name} ${c} ${fmt(v)}`}</title>
                    <rect x={x} y={top} width={bw} height={h} rx={3} fill={PALETTE[k % PALETTE.length]} />
                    {i === categories.length - 1 && (
                      <text x={x + bw / 2} y={v >= 0 ? top - 4 : top + h + 11} textAnchor="middle" fontSize={10} fontWeight={700} fill="#333d4b" className="num">
                        {fmt(v)}
                      </text>
                    )}
                  </g>
                );
              })}
              <text x={pad.l + i * gw + gw / 2} y={H - 6} textAnchor="middle" fontSize={10} fill="#8b95a1">
                {c}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-text-secondary">
        {series.map((s, k) => (
          <span key={s.name} className="flex items-center gap-1">
            <span className="size-2 rounded-sm" style={{ background: PALETTE[k % PALETTE.length] }} />
            {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}
