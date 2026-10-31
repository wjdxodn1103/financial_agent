"use client";

/**
 * 고정 양식의 표·그림 블록 — 섹션 글 뒤 고정 자리(BE app/formats/blocks.py 가 데이터 워크북에서 옮긴 값을 그대로 그린다).
 * 표 칸을 누르면 오른쪽 '문서 보기'에 원본 데이터 칸이 강조되어 열린다. 그림은 라이브러리 없이 SVG 막대 그래프.
 * 표·그림 숫자는 사람이 앱에서 고치지 않는다 — 워드로 내려받아 고치거나(표 수정·차트 데이터 편집) 데이터 엑셀을 고쳐 다시 올린다.
 * AI 채팅 표(BE research/block.py)도 같은 표로 그린다 — 칸마다 자료가 다르고(cell.docId), 글 칸은 인용 문단으로 연다.
 * 작성 화면 밖에서는 onOpen 으로 원문 여는 곳을 받는다.
 * 리서치 차트(BE research/chart.py)는 꺾은선(chartType=line)도 있고, 점·막대를 누르면 원 표 칸의 원문이 열린다(points).
 */
import { useMaybeReportActions } from "../../hooks/useReportStudio";
import type { ChartBlock, ChartPoint, NoteBlock, TableBlock, TableCell } from "../../types";
import { NoteView } from "../assets/NoteView";
import { cn } from "@/lib/utils";

const NAVY = "#1F3A5F";
const LIGHT = "#7A9CC6";
const TOTAL = /합계|총변동|^기금 가치$|투자 포트폴리오 시장가치/;

export type OpenSource = (docId: string, chunk?: string, cell?: [number, number] | null) => void;

function Caption({ block }: { block: TableBlock | ChartBlock }) {
  // 양식 2.0 표는 원본 제목 색(look.captionColor — KIRS 회색), 그 밖은 남색
  const color = block.formId ? block.look?.captionColor || "var(--doc-caption, #1F3A5F)" : undefined;
  return (
    <p className={cn("mt-5 mb-1.5 text-[13px] font-bold", !color && "text-[#1F3A5F]")} style={color ? { color } : undefined}>
      {block.label || block.caption || block.title}
      {block.unitNote ? (
        <span className="float-right text-[11px] font-normal text-text-secondary">(단위: {block.unitNote})</span>
      ) : (
        block.unit && <span className="ml-1 font-normal text-text-secondary">(단위: {block.unit})</span>
      )}
    </p>
  );
}

function Source({ block, onOpen }: { block: TableBlock | ChartBlock; onOpen?: OpenSource }) {
  const actions = useMaybeReportActions();
  const open = onOpen ?? actions?.openDocument;
  if (block.sourceLine)
    return (
      <>
        {block.noteLines?.map((n, i) => (
          <p key={i} className="mt-1 text-[11px] text-text-secondary">
            {n}
          </p>
        ))}
        <p className="mt-1 text-[11px] text-text-secondary">{block.sourceLine}</p>
      </>
    );
  if (!block.docId || !open) return null;
  return (
    <button type="button" onClick={() => open(block.docId!, block.chunk)} className="mt-1 block cursor-pointer text-left text-[11px] text-text-secondary hover:text-primary hover:underline" title="원본 데이터 보기">
      자료: {block.docLabel || "데이터"}
      {block.sourceNo ? ` [${block.sourceNo}]` : ""} · 시트 {block.sheet}
    </button>
  );
}

function Missing({ block }: { block: TableBlock | ChartBlock }) {
  if (block.formId) {
    // 양식 2.0 표 — 행·열은 양식 그대로 두고 칸이 모두 비었다(이 데이터 범위에 맞는 자료가 없다)
    return <div className="rounded-lg border border-dashed border-neutral-300 px-3 py-2.5 text-xs text-text-secondary">이 표에 맞는 자료가 아직 없습니다.</div>;
  }
  return (
    <div className="rounded-lg border border-dashed border-amber-300 bg-amber-50/60 px-3 py-2.5 text-xs text-amber-900">
      데이터 없음 — 성과 데이터 엑셀에 시트 <b>{block.sheet}</b> 를 올리면 채워집니다.
    </div>
  );
}

/** 칸 하나 — 원장 칸·인용 문단으로 이어진 칸은 눌러서 원문을 연다. style = 양식 2.0 열 모양(F 열 글자색·줄무늬 바탕) */
function Cell({ cell, col, docId, open, style }: { cell: TableCell; col: number; docId?: string; open?: OpenSource; style?: React.CSSProperties }) {
  const target = cell.docId ?? docId;
  const align = cell.num ? "text-right" : "text-left";
  if (col === 0 && cell.kind === "head" && (cell.indent || cell.bold || cell.group)) {
    // 양식 2.0 행 이름 — 들여쓰기·굵게(원본 재무표 꼴)
    return (
      <td className={cn("px-2.5 py-1 text-left whitespace-nowrap text-text-primary", (cell.bold || cell.group) && "font-semibold")} style={{ ...(cell.indent ? { paddingLeft: `${0.625 + cell.indent * 0.9}rem` } : {}), ...style }}>
        {cell.text}
      </td>
    );
  }
  if (cell.kind === "empty" || (!cell.text && col > 0)) {
    return (
      <td className={cn("px-2.5 py-1 text-neutral-300", align)} title={cell.title} style={style}>
        –
      </td>
    );
  }
  if (style && col > 0) {
    return (
      <td className={cn("px-2.5 py-1 whitespace-nowrap", align)} style={style} title={cell.title}>
        {(cell.fid || cell.kind === "number") && cell.chunk && target && open ? (
          <button type="button" title={cell.title || "원본 데이터 칸 보기"} onClick={() => open(target, cell.chunk, cell.cell)} className="cursor-pointer rounded px-0.5 hover:bg-primary-soft hover:text-primary">
            {cell.text}
          </button>
        ) : (
          cell.text
        )}
      </td>
    );
  }
  if (cell.kind === "text" && cell.cites?.length && open) {
    return (
      <td className="min-w-[200px] px-2.5 py-1.5 text-left align-top leading-5">
        {cell.text}
        {cell.cites.map((c, i) => (
          <button key={`${c.docId}${c.chunk}${i}`} type="button" title={`${c.label}${c.page ? `, p.${c.page}` : ""}`} onClick={() => open(c.docId, c.chunk)} className="ml-0.5 cursor-pointer align-super text-[10px] text-primary hover:underline">
            [{i + 1}]
          </button>
        ))}
      </td>
    );
  }
  if ((cell.fid || cell.kind === "number") && cell.chunk && target && open) {
    return (
      <td className={cn("px-2.5 py-1", align)}>
        <button type="button" title={cell.title || "원본 데이터 칸 보기"} onClick={() => open(target, cell.chunk, cell.cell)} className="cursor-pointer rounded px-0.5 hover:bg-primary-soft hover:text-primary">
          {cell.text}
        </button>
      </td>
    );
  }
  return (
    <td className={cn("px-2.5 py-1", col === 0 ? "text-left whitespace-nowrap text-text-primary" : align, cell.num && "whitespace-nowrap")} title={cell.title} style={style}>
      {cell.text}
    </td>
  );
}

/** 양식 표의 머리 — 묶음 줄(headGroups)이 있으면 두 줄: 첫 열·묶음 없는 열은 두 줄을 합치고, 묶음은 그 아래 열만큼 */
function FormHead({ block }: { block: TableBlock }) {
  const look = block.look ?? {};
  const style = { background: look.headerFill ?? NAVY, color: look.headerText ?? (look.headerFill ? "#111827" : "#fff") };
  const line = look.lines === "grid" ? "border border-neutral-200" : look.headRule ? "" : "border-b border-neutral-200";
  // 양식 2.0 — 머리 아래 선(원본 색·굵기)·열마다 바탕(머리 칸도 원본처럼 같은 열 바탕)
  const under: React.CSSProperties | undefined = look.headRule ? { borderBottom: `${Math.max(1, (look.headRuleWidth ?? 0.5) * 1.4)}px solid ${look.headRule}` } : undefined;
  const groups = block.headGroups ?? [];
  if (!groups.length) {
    return (
      <thead>
        <tr style={style}>
          {block.header.map((h, i) => (
            <th key={i} className={cn("px-2.5 py-1.5 font-semibold whitespace-nowrap", line, i === 0 ? "text-left" : "text-center")} style={{ ...under, ...(i > 0 && look.columnFills?.[i - 1] ? { background: look.columnFills[i - 1]! } : {}) }}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
    );
  }
  let c = 1;
  const top = groups.map((g, i) => {
    const at = c;
    c += g.span;
    return g.group ? (
      <th key={i} colSpan={g.span} className={cn("px-2.5 py-1 text-center font-semibold whitespace-nowrap", line)}>
        {g.label}
      </th>
    ) : (
      <th key={i} rowSpan={2} className={cn("px-2.5 py-1.5 text-center font-semibold whitespace-nowrap", line)}>
        {block.header[at]}
      </th>
    );
  });
  c = 1;
  const low = groups.flatMap((g) => {
    const at = c;
    c += g.span;
    return g.group
      ? Array.from({ length: g.span }, (_, j) => (
          <th key={at + j} className={cn("px-2.5 py-1 text-center font-medium whitespace-nowrap", line)}>
            {block.header[at + j]}
          </th>
        ))
      : [];
  });
  return (
    <thead style={style}>
      <tr>
        <th rowSpan={2} className={cn("px-2.5 py-1.5 text-left font-semibold whitespace-nowrap", line)}>
          {block.header[0]}
        </th>
        {top}
      </tr>
      <tr>{low}</tr>
    </thead>
  );
}

export function TableBlockView({ block, onOpen, caption = true }: { block: TableBlock; onOpen?: OpenSource; caption?: boolean }) {
  const actions = useMaybeReportActions();
  const open = onOpen ?? actions?.openDocument;
  const look = block.look;
  return (
    <figure data-step={block.step} className="my-1">
      {caption && <Caption block={block} />}
      {block.missing ? (
        <Missing block={block} />
      ) : (
        <div className="overflow-x-auto">
          <table
            className="w-full border-collapse text-[12px] tabular-nums"
            style={look ? { borderTop: `${look.topRuleWidth ? Math.max(1, look.topRuleWidth * 1.4) : 2}px solid ${look.topRule ?? look.rule ?? NAVY}`, borderBottom: `1.5px solid ${look.bottomRule ?? look.rule ?? NAVY}` } : undefined}
          >
            {look ? (
              <FormHead block={block} />
            ) : (
              <thead>
                <tr style={{ background: NAVY }} className="text-white">
                  {block.header.map((h, i) => (
                    <th key={i} className={cn("px-2.5 py-1.5 font-semibold whitespace-nowrap", i === 0 || !block.rows.some((r) => r[i]?.num) ? "text-left" : "text-right")}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {block.rows.map((row, r) => {
                const total = !block.formId && TOTAL.test(row[0]?.text ?? "");
                // 양식 2.0 — 원본 자리(묶음 사이)에만 가로줄, 위·아래 선만인 표는 행 줄 없음
                const groupsOnly = block.formId && (look?.lines === "groups" || look?.lines === "frame" || look?.lines === "none");
                const ruled = groupsOnly && look?.rowRules?.includes(r);
                // 강조 행 — 행 이름 칸의 색을 행 전체 글자에(굵은 행이면 값도 굵게)
                const rc = block.formId ? row[0]?.color : undefined;
                const rowStyle = (c: number): React.CSSProperties | undefined => {
                  const base = block.formId && c > 0 ? colStyle(look, c - 1) : undefined;
                  return rc ? { ...base, color: rc, ...(row[0]?.bold ? { fontWeight: 600 } : {}) } : base;
                };
                return (
                  <tr key={r} className={cn(!groupsOnly && "border-b border-neutral-200", total && "bg-[#EEF2F7] font-semibold")} style={ruled ? { borderBottom: `1px solid ${look?.rule ?? "#7F7F7F"}` } : undefined}>
                    {row.map((cell, c) => (
                      <Cell key={c} cell={cell} col={c} docId={block.docId} open={open} style={rowStyle(c)} />
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <Source block={block} onOpen={onOpen} />
    </figure>
  );
}

/** 양식 2.0 표의 열 모양 — 원본 열 글자색(F 열 빨강)·줄무늬 열 바탕 */
function colStyle(look: TableBlock["look"], j: number): React.CSSProperties | undefined {
  if (!look) return undefined;
  const color = look.columnColors?.[j] ?? undefined;
  const stripe = look.columnFills?.[j] ?? (look.stripeColumns?.includes(j) ? look.stripeColor ?? undefined : undefined);
  return color || stripe ? { color, background: stripe } : undefined;
}

function fmt(v: number, pattern: string): string {
  const d = /\.(0+)/.exec(pattern)?.[1].length ?? 0;
  return v.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: pattern.includes(",") });
}

/** 보기 좋은 축 눈금 — 0 을 포함하는 4~6칸 */
function ticks(min: number, max: number): number[] {
  const lo = Math.min(0, min);
  const hi = Math.max(0, max);
  const span = hi - lo || 1;
  const raw = span / 5;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= 6) ?? raw;
  const out: number[] = [];
  for (let t = Math.floor(lo / step) * step; t <= hi + step * 0.001; t += step) out.push(Math.round(t / step) * step);
  if (out[out.length - 1] < hi) out.push(out[out.length - 1] + step);
  return out;
}

function shortLabel(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/** 진한 색인가('#C00000' 같은 막대 위 값 글자는 흰색 — 누적 막대 조각) */
function dark(hex: string): boolean {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return false;
  const n = parseInt(m[1], 16);
  return 0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255) < 140;
}

function Legend({ block, colorOf }: { block: ChartBlock; colorOf: (j: number) => string }) {
  return (
    <div className="mt-1 flex flex-wrap justify-center gap-x-4 gap-y-1 text-[11px] text-text-secondary">
      {block.series.map((s, j) => {
        const line = s.computed || s.type === "line" || block.chartType === "line" || block.chartType === "band" || (block.chartType === "area" && !s.type);
        const color = s.computed ? bandColor(block) : colorOf(j);
        return (
          <span key={s.name} className="flex items-center gap-1">
            {line ? <span className="inline-block w-3.5 border-t-2" style={{ borderColor: color, borderStyle: s.computed ? "dashed" : "solid" }} /> : <span className="inline-block size-2.5 rounded-[2px]" style={{ background: color }} />}
            {s.name}
            {s.axis === "right" && <span className="text-neutral-400">(오른쪽 축)</span>}
          </span>
        );
      })}
    </div>
  );
}

const FORM_CHARTS = new Set(["area", "pie", "combo", "band"]);

/** 밴드의 계산 띠선 색 — 양식의 둘째 색, 없으면 회색 */
function bandColor(block: ChartBlock): string {
  return block.look?.colors?.[1] ?? "#9CA3AF";
}

/** 양식 차트(문서 양식의 차트 양식) — 영역 · 원 · 막대+선(오른쪽 축) · 밴드(선 + 계산 띠선). 값은 표에 보인 숫자, 점·막대를 누르면 원 칸 */
function FormChartBody({
  block,
  colorOf,
  pointOf,
  openPoint,
  tip,
}: {
  block: ChartBlock;
  colorOf: (j: number) => string;
  pointOf: (j: number, i: number) => ChartPoint | null;
  openPoint: (p: ChartPoint | null) => (() => void) | undefined;
  tip: (s: string, cat: string, v: number, p: ChartPoint | null) => string;
}) {
  const W = 640;
  const H = 250;
  const n = block.categories.length;
  const type = block.chartType;
  const showVals = !!block.look && block.look.labels !== false && n <= 12;
  const grid = block.look?.grid !== false;

  if (type === "pie") {
    const vals = block.series[0]?.values.map((v) => (v != null && v > 0 ? v : 0)) ?? [];
    const total = vals.reduce((a, b) => a + b, 0) || 1;
    const cx = 170;
    const cy = H / 2;
    const r = 100;
    let a0 = -Math.PI / 2;
    return (
      <div className="flex items-center gap-4">
        <svg viewBox={`0 0 340 ${H}`} className="w-[55%]" role="img" aria-label={block.title}>
          {vals.map((v, i) => {
            const a1 = a0 + (v / total) * Math.PI * 2;
            const d = `M${cx},${cy} L${cx + r * Math.cos(a0)},${cy + r * Math.sin(a0)} A${r},${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${cx + r * Math.cos(a1)},${cy + r * Math.sin(a1)} Z`;
            a0 = a1;
            const p = pointOf(0, i);
            const click = openPoint(p);
            return (
              <path key={i} d={d} fill={colorOf(i)} stroke="#fff" strokeWidth={2} onClick={click} className={cn(click && "cursor-pointer hover:opacity-80")}>
                <title>{tip(block.series[0].name, block.categories[i], v, p)}</title>
              </path>
            );
          })}
        </svg>
        <div className="flex flex-col gap-1 text-[11px] text-text-secondary">
          {block.categories.map((c, i) => (
            <span key={c} className="flex items-center gap-1.5">
              <span className="inline-block size-2.5 rounded-[2px]" style={{ background: colorOf(i) }} />
              {c} {vals[i] ? fmt(vals[i], block.number) : "–"}
            </span>
          ))}
        </div>
      </div>
    );
  }

  const left = 52;
  const right = type === "combo" && block.series.some((s) => s.axis === "right") ? 52 : 12;
  const top = 14;
  const bottom = 36;
  const ph = H - top - bottom;
  const scale = (vals: number[]) => {
    const tk = ticks(Math.min(...vals, 0), Math.max(...vals, 0));
    const lo = tk[0];
    const hi = tk[tk.length - 1];
    return { tk, y: (v: number) => top + (1 - (v - lo) / (hi - lo || 1)) * ph };
  };
  const nums = (pick: (s: ChartBlock["series"][number]) => boolean) => block.series.filter(pick).flatMap((s) => s.values.filter((v): v is number => v != null));
  // 밴드는 띠선이 주 계열 범위를 벗어나므로 0 을 꼭 넣지 않는다(밴드 차트는 배수 범위를 본다)
  const L =
    type === "band"
      ? (() => {
          const vals = nums(() => true);
          const tk = ticks(Math.min(...vals) * 0.9, Math.max(...vals) * 1.05).filter((t) => t >= Math.min(...vals) * 0.85);
          const lo = tk[0];
          const hi = tk[tk.length - 1];
          return { tk, y: (v: number) => top + (1 - (v - lo) / (hi - lo || 1)) * ph };
        })()
      : scale(nums((s) => s.axis !== "right"));
  const R = right > 12 ? scale(nums((s) => s.axis === "right")) : null;
  const slot = (W - left - right) / n;
  const cx = (i: number) => left + slot * i + slot / 2;
  const every = Math.max(1, Math.ceil(n / 12));
  const bars = block.series.map((s, j) => ({ s, j })).filter(({ s }) => type === "combo" && (s.type ?? (s.axis === "right" ? "line" : "bar")) === "bar");
  const barW = Math.min(36, (slot * 0.72) / Math.max(1, bars.length));
  const yOf = (s: ChartBlock["series"][number]) => (s.axis === "right" && R ? R.y : L.y);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={block.title}>
      {L.tk.map((t) => (
        <g key={`l${t}`}>
          {grid && <line x1={left} x2={W - right} y1={L.y(t)} y2={L.y(t)} stroke={t === 0 ? "#9CA3AF" : "#E5E7EB"} strokeWidth={t === 0 ? 1 : 0.6} />}
          <text x={left - 6} y={L.y(t) + 3} textAnchor="end" fontSize="10" fill="#6B7280">
            {fmt(t, block.number)}
          </text>
        </g>
      ))}
      {R?.tk.map((t) => (
        <text key={`r${t}`} x={W - right + 6} y={R.y(t) + 3} fontSize="10" fill="#6B7280">
          {fmt(t, block.number)}
        </text>
      ))}
      <line x1={left} x2={W - right} y1={top + ph} y2={top + ph} stroke="#9CA3AF" strokeWidth={1} />
      {block.categories.map((cat, i) =>
        i % every === 0 ? (
          <text key={cat + i} x={cx(i)} y={H - bottom + 15} textAnchor="middle" fontSize="10.5" fill="#374151">
            <title>{cat}</title>
            {shortLabel(cat, Math.max(6, Math.floor((slot * every) / 9)))}
          </text>
        ) : null,
      )}
      {bars.map(({ s, j }, bi) =>
        s.values.map((v, i) => {
          if (v == null) return null;
          const y = yOf(s);
          const x = cx(i) - (barW * bars.length) / 2 + bi * barW;
          const p = pointOf(j, i);
          const click = openPoint(p);
          return (
            <g key={`${j}-${i}`} onClick={click} className={cn(click && "cursor-pointer hover:opacity-80")}>
              <title>{tip(s.name, block.categories[i], v, p)}</title>
              <rect x={x} y={y(Math.max(0, v))} width={Math.max(barW - 2, 1)} height={Math.max(Math.abs(y(v) - y(0)), 0.5)} fill={colorOf(j)} />
              {showVals && (
                <text x={x + (barW - 2) / 2} y={v >= 0 ? y(v) - 4 : y(v) + 11} textAnchor="middle" fontSize="10" fill="#374151">
                  {fmt(v, block.number)}
                </text>
              )}
            </g>
          );
        }),
      )}
      {block.series.map((s, j) => {
        if (bars.some((b) => b.j === j)) return null;
        const y = yOf(s);
        const color = s.computed ? bandColor(block) : colorOf(j);
        const pts = s.values.map((v, i) => (v == null ? null : `${cx(i)},${y(v)}`));
        const runs: string[] = [];
        let cur: string[] = [];
        pts.forEach((pt) => {
          if (pt == null) {
            if (cur.length) runs.push(cur.join(" "));
            cur = [];
          } else cur.push(pt);
        });
        if (cur.length) runs.push(cur.join(" "));
        const area = (type === "area" || s.type === "area") && !s.computed;
        return (
          <g key={s.name}>
            {area &&
              runs.map((r, ri) => {
                const xs = r.split(" ").map((q) => q.split(",")[0]);
                return <polygon key={`a${ri}`} points={`${xs[0]},${y(0)} ${r} ${xs[xs.length - 1]},${y(0)}`} fill={color} opacity={0.18} />;
              })}
            {runs.map((r, ri) => (
              <polyline key={ri} points={r} fill="none" stroke={color} strokeWidth={s.computed ? 1.2 : 2} strokeDasharray={s.computed ? "5 4" : undefined} strokeLinejoin="round" strokeLinecap="round" />
            ))}
            {s.computed && s.values[n - 1] != null && (
              <text x={W - right - 2} y={y(s.values[n - 1]!) - 3} textAnchor="end" fontSize="9.5" fill="#6B7280">
                {s.name.replace("(계산값)", "")}
              </text>
            )}
            {!s.computed &&
              n <= 40 &&
              s.values.map((v, i) => {
                if (v == null) return null;
                const p = pointOf(j, i);
                const click = openPoint(p);
                return (
                  <g key={i} onClick={click} className={cn(click && "cursor-pointer")}>
                    <title>{tip(s.name, block.categories[i], v, p)}</title>
                    <circle cx={cx(i)} cy={y(v)} r={n > 24 ? 2 : 3} fill="#fff" stroke={color} strokeWidth={1.6} />
                    {showVals && (
                      <text x={cx(i)} y={y(v) - 8} textAnchor="middle" fontSize="10" fill="#374151">
                        {fmt(v, block.number)}
                      </text>
                    )}
                  </g>
                );
              })}
          </g>
        );
      })}
    </svg>
  );
}

/** 리서치 에셋 — 표·차트·메모 어느 쪽이든 */
export function AssetBlockView({ block, onOpen, caption = true }: { block: TableBlock | ChartBlock | NoteBlock; onOpen?: OpenSource; caption?: boolean }) {
  if (block.kind === "note") return <NoteView block={block} onOpen={onOpen} />;
  return block.kind === "chart" ? <ChartBlockView block={block} onOpen={onOpen} caption={caption} /> : <TableBlockView block={block} onOpen={onOpen} caption={caption} />;
}

export function ChartBlockView({ block, onOpen, caption = true }: { block: ChartBlock; onOpen?: OpenSource; caption?: boolean }) {
  const actions = useMaybeReportActions();
  const open = onOpen ?? actions?.openDocument;
  // 점·막대 → 원 칸(리서치 차트만 points 가 있다)
  const pointOf = (j: number, i: number): ChartPoint | null => block.points?.[j]?.[i] ?? null;
  const openPoint = (p: ChartPoint | null) => (p?.docId && p.chunk && open ? () => open(p.docId!, p.chunk, p.cell ?? null) : undefined);
  const tip = (s: string, cat: string, v: number, p: ChartPoint | null) => p?.title || `${s} · ${cat} · ${fmt(v, block.number)}`;
  // 누적 막대 — 눈금은 범주마다 쌓은 합까지
  const stacked = !!block.look?.stacked && !block.horizontal && !(block.chartType && FORM_CHARTS.has(block.chartType));
  const values = stacked
    ? block.categories.map((_, i) => block.series.reduce((a, s) => a + Math.max(0, s.values[i] ?? 0), 0))
    : block.series.flatMap((s) => s.values.filter((v): v is number => v != null));
  const tk = ticks(Math.min(...values, 0), Math.max(...values, 0));
  const lo = tk[0];
  const hi = tk[tk.length - 1];
  const colors = block.look?.colors?.length ? block.look.colors : [NAVY, LIGHT];
  const colorOf = (j: number) => colors[j % colors.length];
  const n = block.categories.length;
  const k = block.series.length;
  // 양식 차트는 양식대로(값 글자를 안 쓰는 양식이면 빼고, 범주가 많으면 빼고)
  const showVals = !block.look || (block.look.labels !== false && n <= 12);

  let body: React.ReactNode;
  if (block.chartType && FORM_CHARTS.has(block.chartType)) {
    body = <FormChartBody block={block} colorOf={colorOf} pointOf={pointOf} openPoint={openPoint} tip={tip} />;
  } else if (block.horizontal) {
    const W = 640;
    const left = 120;
    const right = 24;
    const rowH = 26;
    const top = 8;
    const H = top + n * rowH + 28;
    const x = (v: number) => left + ((v - lo) / (hi - lo || 1)) * (W - left - right);
    const barH = Math.min(16, (rowH - 6) / k);
    body = (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={block.title}>
        {tk.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={top} y2={top + n * rowH} stroke={t === 0 ? "#9CA3AF" : "#E5E7EB"} strokeWidth={t === 0 ? 1 : 0.6} />
            <text x={x(t)} y={top + n * rowH + 16} textAnchor="middle" fontSize="10" fill="#6B7280">
              {fmt(t, block.number)}
            </text>
          </g>
        ))}
        {block.categories.map((cat, i) => (
          <g key={cat}>
            <text x={left - 8} y={top + i * rowH + rowH / 2 + 4} textAnchor="end" fontSize="11" fill="#374151">
              <title>{cat}</title>
              {shortLabel(cat, 14)}
            </text>
            {block.series.map((s, j) => {
              const v = s.values[i];
              if (v == null) return null;
              const y = top + i * rowH + (rowH - barH * k) / 2 + j * barH;
              const x0 = x(Math.min(0, v));
              const w = Math.abs(x(v) - x(0));
              const click = openPoint(pointOf(j, i));
              return (
                <g key={s.name} onClick={click} className={cn(click && "cursor-pointer hover:opacity-80")}>
                  <title>{tip(s.name, cat, v, pointOf(j, i))}</title>
                  <rect x={x0} y={y} width={Math.max(w, 0.5)} height={barH - 1} fill={colorOf(j)} />
                  <text x={v >= 0 ? x(v) + 4 : x(v) - 4} y={y + barH / 2 + 3} textAnchor={v >= 0 ? "start" : "end"} fontSize="10" fill="#374151">
                    {fmt(v, block.number)}
                  </text>
                </g>
              );
            })}
          </g>
        ))}
      </svg>
    );
  } else if (block.chartType === "line") {
    // 꺾은선 — 범주는 칸 가운데, 빈 값에서 선을 끊는다, 점을 누르면 원문
    const W = 640;
    const H = 240;
    const left = 52;
    const top = 18;
    const bottom = 40;
    const y = (v: number) => top + (1 - (v - lo) / (hi - lo || 1)) * (H - top - bottom);
    const slot = (W - left - 8) / n;
    const cx = (i: number) => left + slot * i + slot / 2;
    body = (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={block.title}>
        {tk.map((t) => (
          <g key={t}>
            <line x1={left} x2={W - 8} y1={y(t)} y2={y(t)} stroke={t === 0 ? "#9CA3AF" : "#E5E7EB"} strokeWidth={t === 0 ? 1 : 0.6} />
            <text x={left - 6} y={y(t) + 3} textAnchor="end" fontSize="10" fill="#6B7280">
              {fmt(t, block.number)}
            </text>
          </g>
        ))}
        {block.categories.map((cat, i) => (
          <text key={cat} x={cx(i)} y={H - bottom + 16} textAnchor="middle" fontSize="11" fill="#374151">
            <title>{cat}</title>
            {shortLabel(cat, Math.max(6, Math.floor(slot / 11)))}
          </text>
        ))}
        {block.series.map((s, j) => {
          const runs: string[] = [];
          let cur: string[] = [];
          s.values.forEach((v, i) => {
            if (v == null) {
              if (cur.length) runs.push(cur.join(" "));
              cur = [];
            } else cur.push(`${cx(i)},${y(v)}`);
          });
          if (cur.length) runs.push(cur.join(" "));
          return (
            <g key={s.name}>
              {runs.map((pts, r) => (
                <polyline key={r} points={pts} fill="none" stroke={colorOf(j)} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
              ))}
              {s.values.map((v, i) => {
                if (v == null) return null;
                const p = pointOf(j, i);
                const click = openPoint(p);
                return (
                  <g key={i} onClick={click} className={cn(click && "cursor-pointer")}>
                    <title>{tip(s.name, block.categories[i], v, p)}</title>
                    <circle cx={cx(i)} cy={y(v)} r={click ? 4.5 : 3.5} fill="#fff" stroke={colorOf(j)} strokeWidth={2} />
                    {showVals && (
                      <text x={cx(i)} y={y(v) - 9} textAnchor="middle" fontSize="10" fill="#374151">
                        {fmt(v, block.number)}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
    );
  } else {
    const W = 640;
    const H = 240;
    const left = 52;
    const top = 16;
    const bottom = 40;
    const y = (v: number) => top + (1 - (v - lo) / (hi - lo || 1)) * (H - top - bottom);
    const slot = (W - left - 8) / n;
    const barW = stacked ? Math.min(46, slot * 0.6) : Math.min(46, (slot * 0.7) / k);
    body = (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={block.title}>
        {tk.map((t) => (
          <g key={t}>
            <line x1={left} x2={W - 8} y1={y(t)} y2={y(t)} stroke={t === 0 ? "#9CA3AF" : "#E5E7EB"} strokeWidth={t === 0 ? 1 : 0.6} />
            <text x={left - 6} y={y(t) + 3} textAnchor="end" fontSize="10" fill="#6B7280">
              {fmt(t, block.number)}
            </text>
          </g>
        ))}
        {block.categories.map((cat, i) => {
          const cx = left + slot * i + slot / 2;
          let acc = 0;
          return (
            <g key={cat}>
              {block.series.map((s, j) => {
                const v = s.values[i];
                if (v == null) return null;
                const base = stacked ? acc : 0;
                if (stacked) acc += Math.max(0, v);
                const bx = stacked ? cx - barW / 2 : cx - (barW * k) / 2 + j * barW;
                const y0 = y(Math.max(0, v) + base);
                const h = Math.abs(y(v + base) - y(base));
                const click = openPoint(pointOf(j, i));
                return (
                  <g key={s.name} onClick={click} className={cn(click && "cursor-pointer hover:opacity-80")}>
                    <title>{tip(s.name, cat, v, pointOf(j, i))}</title>
                    <rect x={bx} y={y0} width={barW - 2} height={Math.max(h, 0.5)} fill={colorOf(j)} />
                    {showVals && (
                      <text x={bx + (barW - 2) / 2} y={stacked ? y0 + h / 2 + 3.5 : v >= 0 ? y(v) - 4 : y(v) + 11} textAnchor="middle" fontSize="10" fill={stacked && dark(colorOf(j)) ? "#fff" : "#374151"}>
                        {fmt(v, block.number)}
                      </text>
                    )}
                  </g>
                );
              })}
              {stacked && showVals && acc > 0 && (
                <text x={cx - 1} y={y(acc) - 4} textAnchor="middle" fontSize="10" fontWeight={600} fill="#374151">
                  {fmt(acc, block.number)}
                </text>
              )}
              <text x={cx} y={H - bottom + 16} textAnchor="middle" fontSize="11" fill="#374151">
                <title>{cat}</title>
                {shortLabel(cat, Math.max(6, Math.floor(slot / 11)))}
              </text>
            </g>
          );
        })}
      </svg>
    );
  }

  return (
    <figure data-step={block.step} className="my-1">
      {caption ? <Caption block={block} /> : block.unit && <p className="mb-1 text-right text-[11px] text-text-secondary">단위: {block.unit}</p>}
      {block.missing ? (
        <Missing block={block} />
      ) : (
        <>
          {k > 1 && block.chartType !== "pie" && block.legend === "top" && <Legend block={block} colorOf={colorOf} />}
          {block.unit2 && (
            <div className="flex justify-between text-[11px] text-text-secondary">
              <span>({block.unit})</span>
              <span>(오른쪽 축 {block.unit2})</span>
            </div>
          )}
          {body}
          {k > 1 && block.chartType !== "pie" && block.legend !== "top" && <Legend block={block} colorOf={colorOf} />}
        </>
      )}
      <Source block={block} onOpen={onOpen} />
    </figure>
  );
}
