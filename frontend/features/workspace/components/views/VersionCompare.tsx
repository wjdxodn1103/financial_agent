"use client";

/**
 * 자료 판 비교 — 같은 자료의 두 판 원장(표 칸 숫자)을 맞춰 바뀜·새로 생김·없어짐을 보여 준다(BE 코드 비교, AI 아님).
 * 값을 누르면 그 판의 원문 칸이 열린다(이전 판은 보관본이라 원문 보기만 된다).
 */
import { useEffect, useState } from "react";
import { ArrowRight, History, Loader2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { compareVersions } from "../../../report/api";
import type { DocumentCard, VersionCompareResult, VersionRef } from "../../../report/types";

export interface VersionView {
  card: DocumentCard;
  chunk?: string;
  cell?: [number, number] | null;
}

/** 보관된 이전 판에는 자료 카드가 없다 — 뷰어에 넘길 최소 카드 */
export function archivedCard(docId: string, label: string, fileName: string): DocumentCard {
  return {
    id: docId,
    label,
    title: label,
    docType: "",
    date: "",
    issuer: "",
    company: "",
    oneLine: "보관된 이전 판(원문 보기만)",
    fileName,
    fileType: fileName.split(".").pop() ?? "",
    pageCount: null,
    chunkCount: 0,
    paragraphCount: 0,
    embedded: true,
    enriched: true,
  };
}

function delta(v: number, percent: boolean): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "±";
  const a = Math.abs(v);
  if (percent) return `${sign}${a.toFixed(1)}%p`;
  if (a >= 1e12) return `${sign}${(a / 1e12).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}조원`;
  if (a >= 1e8) return `${sign}${(a / 1e8).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}억원`;
  return `${sign}${a.toLocaleString("ko-KR")}`;
}

export function VersionCompare({ workspaceId, doc, onView, onClose }: { workspaceId: string; doc: DocumentCard; onView: (v: VersionView) => void; onClose: () => void }) {
  const [res, setRes] = useState<VersionCompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const history = doc.version?.history ?? [];

  useEffect(() => {
    let cancelled = false;
    setRes(null);
    setError(null);
    compareVersions(workspaceId, doc.id)
      .then((r) => !cancelled && setRes(r))
      .catch(() => !cancelled && setError("비교하지 못했습니다."));
    return () => {
      cancelled = true;
    };
  }, [doc.id, workspaceId]);

  const open = (ref: VersionRef) => {
    const h = history.find((x) => x.docId === ref.docId);
    const card = ref.docId === doc.id ? doc : archivedCard(ref.docId, h ? `${h.label} (v${h.version})` : ref.docId, h?.fileName ?? "");
    onView({ card, chunk: ref.chunk, cell: ref.cell });
  };

  const Val = ({ r, strike }: { r: VersionRef; strike?: boolean }) => (
    <button type="button" onClick={() => open(r)} title="원문 칸 보기" className={cn("cursor-pointer rounded px-1 font-medium tabular-nums hover:bg-primary-soft hover:text-primary", strike && "text-text-secondary line-through")}>
      {r.display}
    </button>
  );

  return (
    <div className="thin-scrollbar flex min-h-0 flex-1 flex-col overflow-y-auto px-6 py-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-lg font-semibold text-text-primary">
            <History className="size-4 text-primary" aria-hidden />판 비교 — 숫자 변경
          </h2>
          <p className="mt-0.5 text-xs text-text-secondary">두 판의 표 칸 숫자를 지표·기간·기준으로 맞춰 비교했습니다(코드 비교). 값을 누르면 원문 칸이 열립니다.</p>
        </div>
        <button type="button" aria-label="비교 닫기" onClick={onClose} className="cursor-pointer rounded p-1 text-text-secondary hover:bg-neutral-100">
          <X className="size-4" aria-hidden />
        </button>
      </div>

      <ol className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
        {history.map((h, i) => (
          <li key={h.docId} className="flex items-center gap-1.5">
            {i > 0 && <ArrowRight className="size-3 text-text-secondary" aria-hidden />}
            <button
              type="button"
              onClick={() => onView({ card: h.docId === doc.id ? doc : archivedCard(h.docId, `${h.label} (v${h.version})`, h.fileName) })}
              className={cn("cursor-pointer rounded-full border px-2 py-0.5 hover:bg-neutral-50", h.docId === doc.id ? "border-primary-soft-border bg-primary-soft text-primary" : "border-neutral-200 text-text-secondary")}
            >
              v{h.version} · {h.fileName || h.label}
            </button>
          </li>
        ))}
      </ol>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      {!res && !error && (
        <p className="mt-4 flex items-center gap-1.5 text-sm text-text-secondary">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          비교하는 중…
        </p>
      )}
      {res && (
        <>
          <p className="mt-4 text-sm text-text-primary">
            <span className="font-medium">{res.old.label}</span> → <span className="font-medium">{res.new.label}</span>
            <span className="ml-2 text-xs text-text-secondary">
              바뀜 {res.changed.length} · 새로 생김 {res.added.length} · 없어짐 {res.removed.length} · 그대로 {res.same}
            </span>
          </p>
          <div className="mt-3 overflow-hidden rounded-xl border border-neutral-200">
            <div className="grid grid-cols-[minmax(0,1.4fr)_5rem_4rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)] gap-2 border-b border-neutral-200 bg-background-gray px-4 py-2 text-[11px] font-semibold text-text-secondary">
              <span>지표</span>
              <span>기간</span>
              <span>기준</span>
              <span>이전 판</span>
              <span>새 판</span>
              <span>차이</span>
            </div>
            {res.changed.length + res.added.length + res.removed.length === 0 && <p className="px-4 py-5 text-sm text-text-secondary">표 칸 숫자는 바뀐 것이 없습니다.</p>}
            {res.changed.map((x, i) => (
              <div key={`c${i}`} className="grid grid-cols-[minmax(0,1.4fr)_5rem_4rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)] items-center gap-2 border-b border-neutral-100 bg-amber-50/50 px-4 py-2 text-sm last:border-b-0">
                <span className="truncate text-text-primary">{x.metric}</span>
                <span className="text-text-secondary">{x.period}</span>
                <span className="text-text-secondary">{x.basis ?? "—"}</span>
                <span>
                  <Val r={x.before} strike />
                </span>
                <span>
                  <Val r={x.after} />
                </span>
                <span className={cn("text-xs font-medium tabular-nums", x.delta < 0 ? "text-red-600" : "text-emerald-700")}>{delta(x.delta, x.percent)}</span>
              </div>
            ))}
            {res.added.map((x, i) => (
              <div key={`a${i}`} className="grid grid-cols-[minmax(0,1.4fr)_5rem_4rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)] items-center gap-2 border-b border-neutral-100 px-4 py-2 text-sm last:border-b-0">
                <span className="truncate text-text-primary">{x.metric}</span>
                <span className="text-text-secondary">{x.period}</span>
                <span className="text-text-secondary">{x.basis ?? "—"}</span>
                <span className="text-xs text-text-secondary">—</span>
                <span>
                  <Val r={x.after} />
                </span>
                <span className="text-xs text-emerald-700">새로 생김</span>
              </div>
            ))}
            {res.removed.map((x, i) => (
              <div key={`r${i}`} className="grid grid-cols-[minmax(0,1.4fr)_5rem_4rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)] items-center gap-2 border-b border-neutral-100 px-4 py-2 text-sm last:border-b-0">
                <span className="truncate text-text-primary">{x.metric}</span>
                <span className="text-text-secondary">{x.period}</span>
                <span className="text-text-secondary">{x.basis ?? "—"}</span>
                <span>
                  <Val r={x.before} strike />
                </span>
                <span className="text-xs text-text-secondary">—</span>
                <span className="text-xs text-red-600">없어짐</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-text-secondary">문장 속 숫자는 비교하지 않습니다 — 새 판을 검수하면 앞선 검수 지적이 해소됐는지 함께 봅니다.</p>
        </>
      )}
    </div>
  );
}
