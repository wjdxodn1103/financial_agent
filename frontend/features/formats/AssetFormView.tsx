"use client";

/**
 * 표·차트 양식(에셋) 미리보기 — 샘플에서 뽑은 형식(구성 + 겉모양)대로 빈 틀을 그린다. 값은 자리 값(표 '0.0', 차트는 모양만 보이는 예시 선·막대)이고
 * 행 이름은 '{행 종류} 1…' — 내용이 아니라 꼴을 보이는 화면이다. 실제 값은 문서를 쓸 때 데이터로 채운다.
 * 보조축(combo)·띠선(band)은 샘플의 형식을 그대로 옮긴 것이다(값이 없는 틀이라 눈금 숫자도 그리지 않는다).
 */
import type { FormatAsset } from "./types";

const PALETTE = ["#1F3A5F", "#7A9CC6", "#C77B30", "#8A9BA8", "#4F7A5A", "#B0B7C3"];
const ROW_MAX = 6;

function captionText(a: FormatAsset, n: number): string {
  return a.caption.numbered && a.caption.label ? `${a.caption.label} ${n}. ${a.name}` : a.caption.label ? `${a.caption.label}. ${a.name}` : a.name;
}

export function AssetFormView({ asset, n }: { asset: FormatAsset; n: number }) {
  const cap = captionText(asset, n);
  return (
    <figure className="min-w-0">
      <figcaption className="mb-1.5 text-[13px]" style={{ fontWeight: asset.look.captionBold === false ? 400 : 700, color: asset.look.captionColor ?? "#111827" }}>
        {cap}
      </figcaption>
      {asset.kind === "table" && asset.table ? <TableForm asset={asset} /> : asset.chart ? <ChartForm asset={asset} /> : null}
      {(asset.note || asset.sourceLine) && (
        <div className="mt-1 space-y-0.5 text-[11px] text-neutral-500">
          {asset.note && <p>주: …</p>}
          {asset.sourceLine && <p>자료: …</p>}
        </div>
      )}
    </figure>
  );
}

function TableForm({ asset }: { asset: FormatAsset }) {
  const t = asset.table!;
  const look = asset.look;
  const rule = look.rule ?? "#1F3A5F";
  const lines = look.lines ?? "horizontal";
  const align = look.numberAlign ?? "right";
  const two = t.groups.some((g) => g.label && (g.columns.length > 1 || g.columns[0] !== g.label));
  const cols = t.groups.flatMap((g) => g.columns.map((c) => ({ c, unit: g.label ? "" : g.unit })));
  const rows = Math.min(t.rows, ROW_MAX);
  const cell = lines === "grid" ? "border border-neutral-200" : lines === "horizontal" ? "border-b border-neutral-200" : "";
  const head = { background: look.headerFill ?? "#F3F5F8", color: look.headerText ?? "#111827" };
  const withUnit = (label: string, unit: string) => (unit ? `${label} (${unit})` : label);
  return (
    <div className="thin-scrollbar overflow-x-auto">
      <table className="w-full border-collapse text-[11.5px]" style={{ borderTop: `2px solid ${rule}`, borderBottom: `1.5px solid ${rule}` }}>
        <thead>
          <tr>
            <th rowSpan={two ? 2 : 1} className={`px-2 py-1.5 text-left font-semibold whitespace-nowrap ${cell}`} style={head}>
              {t.stub || t.rowKind || "항목"}
            </th>
            {t.groups.map((g, i) =>
              two && g.label && (g.columns.length > 1 || g.columns[0] !== g.label) ? (
                <th key={i} colSpan={g.columns.length} className={`px-2 py-1 text-center font-semibold whitespace-nowrap ${cell}`} style={head}>
                  {withUnit(g.label, g.unit)}
                </th>
              ) : (
                g.columns.map((c, k) => (
                  <th key={`${i}-${k}`} rowSpan={two ? 2 : 1} className={`px-2 py-1.5 text-center font-semibold whitespace-nowrap ${cell}`} style={head}>
                    {withUnit(c, g.unit)}
                  </th>
                ))
              ),
            )}
          </tr>
          {two && (
            <tr>
              {t.groups
                .filter((g) => g.label && (g.columns.length > 1 || g.columns[0] !== g.label))
                .flatMap((g, i) =>
                  g.columns.map((c, k) => (
                    <th key={`${i}-${k}`} className={`px-2 py-1 text-center font-medium whitespace-nowrap ${cell}`} style={head}>
                      {c}
                    </th>
                  )),
                )}
            </tr>
          )}
        </thead>
        <tbody>
          {Array.from({ length: rows }, (_, r) => (
            <tr key={r}>
              <td className={`px-2 py-1 whitespace-nowrap text-neutral-600 ${cell}`}>
                {t.rowKind || "항목"} {r + 1}
              </td>
              {cols.map((_, k) => (
                <td key={k} className={`px-2 py-1 text-neutral-300 tabular-nums ${cell}`} style={{ textAlign: align }}>
                  0.0
                </td>
              ))}
            </tr>
          ))}
          {t.rows > rows && (
            <tr>
              <td colSpan={cols.length + 1} className="px-2 py-1 text-center text-[11px] text-neutral-400">
                ⋯ 샘플은 {t.rows}행
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** 모양만 보이는 예시 값 — 계열마다 다른 결의 완만한 선(0~1) */
function wave(j: number, n: number): number[] {
  return Array.from({ length: n }, (_, i) => 0.45 + 0.22 * Math.sin((i + 1) * (0.55 + j * 0.23) + j * 1.7) + 0.1 * Math.sin(i * 1.9 + j) + (j % 2 ? -0.08 : 0.06));
}

function ChartForm({ asset }: { asset: FormatAsset }) {
  const c = asset.chart!;
  const colors = asset.look.colors?.length ? asset.look.colors : PALETTE;
  const series = c.series.length ? c.series : [{ name: asset.name, type: c.type === "bar" || c.type === "barh" ? ("bar" as const) : ("line" as const), axis: "left" as const }];
  const grid = asset.look.grid !== false;
  const W = 560;
  const H = 220;
  const L = 34;
  const R = c.unit2 ? 34 : 12;
  const T = 16;
  const B = 24;
  const pw = W - L - R;
  const ph = H - T - B;
  const n = c.x === "date" ? 24 : 6;
  const y = (v: number) => T + (1 - v) * ph;
  const lineOf = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${(L + (pw * (i + 0.5)) / vals.length).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const legend = c.legend !== "none" && series.length > 1;
  const color = (j: number) => colors[j % colors.length];

  let marks: React.ReactNode;
  if (c.type === "pie") {
    const k = Math.max(series.length, 4);
    const cx = W / 2;
    const cy = T + ph / 2;
    const r = ph / 2;
    let a0 = -Math.PI / 2;
    marks = Array.from({ length: k }, (_, j) => {
      const share = (k - j) / ((k * (k + 1)) / 2);
      const a1 = a0 + share * Math.PI * 2;
      const d = `M${cx},${cy} L${cx + r * Math.cos(a0)},${cy + r * Math.sin(a0)} A${r},${r} 0 ${share > 0.5 ? 1 : 0} 1 ${cx + r * Math.cos(a1)},${cy + r * Math.sin(a1)} Z`;
      a0 = a1;
      return <path key={j} d={d} fill={color(j)} stroke="#fff" strokeWidth={2} />;
    });
  } else if (c.type === "barh") {
    const rows = 6;
    const rowH = ph / rows;
    const k = series.length;
    const barH = Math.min(12, (rowH - 4) / k);
    marks = Array.from({ length: rows }, (_, i) =>
      series.map((_, j) => {
        const v = wave(j, rows)[i];
        return <rect key={`${i}-${j}`} x={L} y={T + i * rowH + (rowH - barH * k) / 2 + j * barH} width={pw * v * 0.9} height={barH - 1} rx={2} fill={color(j)} />;
      }),
    );
  } else if (c.type === "band") {
    // 띠선 계열을 따로 읽지 못했으면(계열 하나) 평균·±1·±2 표준편차 띠 넷을 그린다
    const main = wave(0, n);
    const bands = series.length > 1 ? series.slice(1) : ["평균", "+1SD", "-1SD", "+2SD", "-2SD"].map((name) => ({ name, type: "line" as const, axis: "left" as const }));
    marks = (
      <>
        {bands.map((s, j) => {
          const off = [0, 0.18, -0.18, 0.34, -0.34][j] ?? (j % 2 ? -0.1 * j : 0.1 * j);
          const v0 = 0.45 + off;
          return <line key={s.name} x1={L} x2={L + pw} y1={y(v0 - 0.05)} y2={y(v0 + 0.05)} stroke={colors[1] ?? "#9CA3AF"} strokeWidth={1.2} strokeDasharray="4 3" />;
        })}
        <path d={lineOf(main)} fill="none" stroke={color(0)} strokeWidth={2} strokeLinejoin="round" />
      </>
    );
  } else {
    const bars = series.map((s, j) => ({ s, j })).filter(({ s }) => c.type === "bar" || (c.type === "combo" && s.type === "bar"));
    const lines = series.map((s, j) => ({ s, j })).filter(({ s }) => !bars.some((b) => b.s === s));
    const slot = pw / n;
    const bw = Math.min(18, (slot * 0.7) / Math.max(bars.length, 1));
    marks = (
      <>
        {bars.map(({ s, j }, bi) =>
          wave(j, n).map((v, i) => {
            const x = L + slot * i + (slot - bw * bars.length) / 2 + bi * bw;
            return <rect key={`${s.name}-${i}`} x={x} y={y(v * 0.9)} width={Math.max(bw - 2, 1)} height={y(0) - y(v * 0.9)} rx={2} fill={color(j)} />;
          }),
        )}
        {lines.map(({ s, j }) => {
          const vals = wave(j, n);
          return (
            <g key={s.name}>
              {s.type === "area" || c.type === "area" ? <path d={`${lineOf(vals)} L${L + pw - pw / n / 2},${y(0)} L${L + pw / n / 2},${y(0)} Z`} fill={color(j)} opacity={0.15} /> : null}
              <path d={lineOf(vals)} fill="none" stroke={color(j)} strokeWidth={2} strokeLinejoin="round" />
            </g>
          );
        })}
      </>
    );
  }

  const describe = `${asset.name} — ${series.map((s) => s.name).join(", ")}`;
  return (
    <div>
      {legend && c.legend === "top" && <Legend series={series} color={color} chartType={c.type} />}
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={describe}>
        {c.type !== "pie" && (
          <>
            {grid && [0.25, 0.5, 0.75, 1].map((g) => <line key={g} x1={L} x2={L + pw} y1={y(g)} y2={y(g)} stroke="#E5E7EB" strokeWidth={0.6} />)}
            <line x1={L} x2={L + pw} y1={y(0)} y2={y(0)} stroke="#9CA3AF" strokeWidth={1} />
            {c.unit && (
              <text x={4} y={T - 4} fontSize="10" fill="#6B7280">
                ({c.unit})
              </text>
            )}
            {c.unit2 && (
              <text x={W - 4} y={T - 4} textAnchor="end" fontSize="10" fill="#6B7280">
                ({c.unit2})
              </text>
            )}
            {c.type !== "barh" && (
              <text x={L + pw / 2} y={H - 6} textAnchor="middle" fontSize="10" fill="#9CA3AF">
                {c.x === "date" ? "날짜" : c.x === "period" ? "기간" : "항목"}
              </text>
            )}
          </>
        )}
        {marks}
      </svg>
      {legend && c.legend !== "top" && <Legend series={series} color={color} chartType={c.type} />}
    </div>
  );
}

function Legend({ series, color, chartType }: { series: NonNullable<FormatAsset["chart"]>["series"]; color: (j: number) => string; chartType: string }) {
  return (
    <div className="my-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-neutral-600">
      {series.map((s, j) => (
        <span key={`${s.name}-${j}`} className="flex items-center gap-1">
          {s.type === "bar" || chartType === "bar" || chartType === "barh" ? <span className="size-2.5 rounded-[2px]" style={{ background: color(j) }} /> : <span className="h-0.5 w-3.5" style={{ background: color(j) }} />}
          {s.name}
          {s.axis === "right" && <span className="text-neutral-400">(오른쪽 축)</span>}
        </span>
      ))}
    </div>
  );
}
