"use client";

/**
 * 자리 미리보기 — 섹션 뒤 표·차트 자리가 어떤 모양으로 들어갈지(머리·행 이름만). 값은 문서를 쓸 때 자료에서 채운다.
 * 설명 자리(샘플 분석·화면에서 더한 것, 표 양식 없음)는 이름과 구성 한 줄만.
 * 차트는 같은 높이의 흐린 막대·평평한 선 — 값처럼 읽히지 않게 모양만.
 */
import { BarChart3, ImageIcon, LineChart, Table2 } from "lucide-react";

import type { ResearchTemplate } from "../research/types";
import type { FormatSlot } from "./types";

const SUBJECT_LABEL: Record<string, string> = { company: "기업", document: "문서", period: "기간", label: "항목" };

function rowLabels(slot: FormatSlot, t: ResearchTemplate): { labels: string[]; open: boolean } {
  const fixed = t.spec.rows?.map((r) => r.label) ?? (slot.rows?.length ? slot.rows : null);
  return fixed ? { labels: fixed, open: false } : { labels: [], open: true };
}

export function SlotPreview({ slot, template }: { slot: FormatSlot; template?: ResearchTemplate }) {
  const Icon = slot.kind === "figure" ? ImageIcon : slot.kind === "chart" ? (template?.spec.chart?.type === "line" ? LineChart : BarChart3) : Table2;
  return (
    <div className="rounded-2xl bg-white p-4 ring-1 ring-neutral-200">
      <p className="flex items-center gap-1.5 text-[13px] font-semibold text-text-primary">
        <Icon className="size-4 shrink-0 text-primary" aria-hidden />
        <span className="truncate">{slot.title}</span>
      </p>
      {slot.kind === "figure" ? (
        <div className="mt-3 flex h-36 items-center justify-center rounded-xl border border-dashed border-neutral-300 text-[12px] text-neutral-500">그림 자리</div>
      ) : !template ? (
        <p className="mt-3 text-[12px] leading-5 text-text-secondary">
          {slot.builtin ? "기본 양식에 고정된 표·그림입니다." : slot.desc || (slot.templateId ? "이 표 양식을 볼 수 없습니다." : "구성 설명 없음")}
          {slot.position === "sidebar" && <span className="ml-1.5 rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-600">옆 칸</span>}
        </p>
      ) : slot.kind === "chart" ? (
        <ChartShape slot={slot} t={template} />
      ) : (
        <TableShape slot={slot} t={template} />
      )}
      {template && (
        <p className="mt-2 truncate text-[12px] text-text-secondary">
          표 양식: {template.name}
          {rowLabels(slot, template).open && ` · 행(${SUBJECT_LABEL[template.spec.subject.kind] ?? template.spec.subject.label})은 쓸 때 정함`}
        </p>
      )}
    </div>
  );
}

function TableShape({ slot, t }: { slot: FormatSlot; t: ResearchTemplate }) {
  const cols = t.spec.items.filter((i) => !i.hidden).map((i) => (i.unit ? `${i.label}(${i.unit})` : i.label));
  const { labels, open } = rowLabels(slot, t);
  const rows = open ? ["…", "…", "…"] : labels.slice(0, 12);
  const subject = t.spec.subject.label || SUBJECT_LABEL[t.spec.subject.kind] || "항목";
  // 방향이 '열 = 대상'이면 대상이 머리로 간다
  const flip = t.spec.orientation === "items_as_rows";
  const head = flip ? [t.spec.itemsOpen ? "항목" : "", ...rows] : [subject, ...(t.spec.itemsOpen ? ["…"] : cols)];
  const body = flip ? (t.spec.itemsOpen ? ["…"] : cols) : rows;
  const width = head.length - 1;
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full border-collapse text-[12px]">
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={i} className="border-y border-neutral-300 bg-neutral-50 px-2 py-1.5 text-left font-semibold whitespace-nowrap text-neutral-700">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((r, i) => (
            <tr key={i}>
              <td className="border-b border-neutral-200 px-2 py-1.5 whitespace-nowrap text-neutral-700">{r}</td>
              {Array.from({ length: width }, (_, j) => (
                <td key={j} className="border-b border-neutral-200 px-2 py-1.5 text-right text-neutral-300">
                  —
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!open && labels.length > rows.length && <p className="mt-1 text-[11px] text-neutral-500">외 {labels.length - rows.length}행</p>}
    </div>
  );
}

function ChartShape({ slot, t }: { slot: FormatSlot; t: ResearchTemplate }) {
  const series = t.spec.chart?.seriesLabels?.length ? t.spec.chart.seriesLabels : t.spec.items.filter((i) => !i.hidden && i.type !== "text").map((i) => i.label);
  const { labels, open } = rowLabels(slot, t);
  const cats = open ? ["", "", "", ""] : labels.slice(0, 8);
  const line = t.spec.chart?.type === "line";
  const W = 320;
  const H = 120;
  const step = W / Math.max(cats.length, 1);
  const tones = ["#cbd5e1", "#e2e8f0", "#94a3b8"];
  return (
    <div className="mt-3">
      <svg viewBox={`0 0 ${W} ${H + 18}`} className="w-full" role="img" aria-label="차트 모양">
        <line x1={0} y1={H} x2={W} y2={H} stroke="#d4d4d4" />
        {line
          ? series.slice(0, 3).map((_, si) => <line key={si} x1={step / 2} x2={W - step / 2} y1={40 + si * 22} y2={40 + si * 22} stroke={tones[si]} strokeWidth={2} strokeDasharray="5 4" />)
          : cats.map((_, ci) =>
              series.slice(0, 3).map((__, si) => {
                const n = Math.min(series.length, 3);
                const bw = (step * 0.7) / n;
                return <rect key={`${ci}-${si}`} x={ci * step + step * 0.15 + si * bw} y={36} width={bw - 2} height={H - 36} fill={tones[si]} rx={2} />;
              }),
            )}
        {cats.map((c, ci) => (
          <text key={ci} x={ci * step + step / 2} y={H + 13} textAnchor="middle" fontSize={10} fill="#737373">
            {c.length > 8 ? `${c.slice(0, 7)}…` : c}
          </text>
        ))}
      </svg>
      <p className="mt-1 truncate text-[12px] text-text-secondary">
        {line ? "꺾은선" : "막대"} · 계열: {series.join(" · ") || "—"}
      </p>
    </div>
  );
}
