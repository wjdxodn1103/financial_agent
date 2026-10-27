"use client";

/** 자료 패널 행 프리미티브 — 파일 타입 배지·폴더 머리(OP-FE library/AssetRow.tsx 의 FileTypeIcon·FolderRow 그대로) + 데이터 한 줄 정보(업로드 시점·크기). */
import { ChevronDown, ChevronRight, Folder, FolderOpen } from "lucide-react";

import { cn } from "@/lib/utils";
import type { DocumentCard } from "../../types";

export function formatSize(bytes?: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

export function formatWhen(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

/** 데이터 한 줄 정보 — 업로드 시점 · 파일 크기 */
export function fileMeta(d: DocumentCard): string {
  return [formatWhen(d.uploadedAt ?? d.createdAt), formatSize(d.size)].filter(Boolean).join(" · ");
}

export function FileTypeIcon({ type }: { type: string }) {
  const t = (type || "").toUpperCase();
  const color = t === "PDF" ? "bg-rose-500" : t === "DOCX" ? "bg-sky-600" : t === "MD" || t === "TXT" ? "bg-slate-500" : "bg-emerald-600";
  return (
    <span className="relative flex h-8 w-7 shrink-0 items-center justify-center rounded-md text-white" aria-hidden>
      <span className={cn("absolute inset-0 rounded-md opacity-90", color)} />
      <span className="relative font-mono text-[0.5rem] font-bold">{t.slice(0, 4)}</span>
    </span>
  );
}

export function FolderRow({ open, label, count, extra, onClick }: { open: boolean; label: string; count?: number; extra?: string; onClick: () => void }) {
  const Icon = open ? FolderOpen : Folder;
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <button type="button" onClick={onClick} aria-expanded={open} className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-neutral-100">
      <Chevron className="size-4 shrink-0 text-text-secondary" aria-hidden />
      <Icon className="size-4 shrink-0 text-primary" aria-hidden />
      <span className="min-w-0 flex-1 truncate text-sm font-medium text-text-primary">{label}</span>
      {extra && <span className="shrink-0 text-xs text-text-secondary">{extra}</span>}
      {count !== undefined && <span className="shrink-0 font-mono text-xs font-medium text-primary">{count}</span>}
    </button>
  );
}
