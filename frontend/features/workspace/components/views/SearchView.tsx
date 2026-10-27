"use client";

/**
 * 통합 검색 — 워크스페이스 안 에셋(표·차트)·문서·데이터 파일·폴더(이름) + 자료 문단·근거 원장·팀 기록·리포트·채널·작업 항목을 한 검색창에서.
 * 자료 문단·원장·데이터 파일은 오른쪽에 원문을 바로 연다. 나머지는 해당 화면으로 간다. 워크스페이스 밖은 찾지 않는다.
 */
import { useEffect, useRef, useState } from "react";
import { BarChart3, ClipboardList, FileSpreadsheet, FileText, Folder, FolderOpen, ListTodo, Loader2, MessagesSquare, Search, Table2, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import { DocViewerBody } from "../../../report/components/viewer/DocViewerBody";
import { searchWorkspace } from "../../api";
import { useWorkspace } from "../../context";
import { FEATURES } from "../../features";
import { useWorkspaceDocuments } from "../../hooks/useWorkspaceDocuments";
import type { SearchItem, SearchResult } from "../../types";
import { AssetDrawer } from "./AssetsView";

const ICON: Record<SearchItem["kind"], LucideIcon> = {
  asset: BarChart3,
  doc: FileText,
  file: FileSpreadsheet,
  folder: Folder,
  document: FolderOpen,
  figure: Table2,
  record: ClipboardList,
  report: FileText,
  message: MessagesSquare,
  task: ListTodo,
};

function when(iso?: string | null): string {
  return iso ? new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
}

export function SearchView({ query = "" }: { query?: string }) {
  const ws = useWorkspace();
  const docs = useWorkspaceDocuments(ws.workspaceId, false);
  const [q, setQ] = useState(query);
  const [res, setRes] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<{ docId: string; chunk?: string | null; cell?: [number, number] | null; tick: number } | null>(null);
  const [tableOpen, setTableOpen] = useState<string | null>(null);
  const seq = useRef(0);

  const run = async (text: string) => {
    if (!text.trim()) return;
    const n = ++seq.current;
    setBusy(true);
    try {
      const r = await searchWorkspace(ws.workspaceId, text);
      if (n === seq.current) setRes(r);
    } finally {
      if (n === seq.current) setBusy(false);
    }
  };

  // 위쪽 검색창에서 온 검색어 — 바뀔 때마다 바로 찾는다
  useEffect(() => {
    setQ(query);
    setView(null);
    if (query.trim()) void run(query);
    else setRes(null);
  }, [query, ws.workspaceId]);

  const open = (it: SearchItem) => {
    if ((it.kind === "document" || it.kind === "figure" || it.kind === "file") && it.docId) {
      setTableOpen(null);
      setView((v) => ({ docId: it.docId!, chunk: it.chunk, cell: it.cell ?? null, tick: (v?.tick ?? 0) + 1 }));
    } else if (it.kind === "asset" && it.id) {
      // 에셋을 끈 동안 — 내 작업에서 만든 것은 그 작업(결과)에서, 아니면 오른쪽 미리보기
      if (FEATURES.assets) ws.nav.openAsset(it.id);
      else if (it.taskId) ws.nav.openReport(it.taskId, it.id);
      else setTableOpen(it.id);
    }
    else if (it.kind === "folder" && it.id) ws.nav.openFolder(it.id);
    else if ((it.kind === "report" || it.kind === "doc") && it.reportId) ws.nav.openReport(it.reportId);
    else if (it.kind === "task") ws.nav.view("tasks");
    else ws.nav.view("channel");
  };

  const viewDoc = view ? (docs.documents ?? []).find((d) => d.id === view.docId) : null;
  const total = res?.groups.reduce((n, g) => n + g.items.length, 0) ?? 0;

  return (
    <div className="flex min-h-0 flex-1">
      <section className="thin-scrollbar flex min-w-0 flex-1 flex-col overflow-y-auto px-6 py-6">
        <h1 className="text-[26px] leading-tight font-bold tracking-tight text-text-primary">통합 검색</h1>
        <p className="mt-1 text-sm text-text-secondary">이 워크스페이스의 표·차트·문서·데이터·폴더와 자료 문단·근거 원장·팀 기록·할 일을 한 번에 찾습니다(워크스페이스 밖은 찾지 않습니다).</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(q);
          }}
          className="mt-4 flex items-center gap-2 rounded-xl border border-neutral-200 px-3 py-2 focus-within:border-primary"
        >
          <Search className="size-4 text-text-secondary" aria-hidden />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="예: 매출 2024 · 금리 · EBITDA" className="min-w-0 flex-1 text-sm outline-none" aria-label="검색어" />
          {busy && <Loader2 className="size-4 animate-spin text-text-secondary" aria-hidden />}
          <button type="submit" disabled={!q.trim()} className="cursor-pointer rounded-md bg-primary px-3 py-1 text-xs text-white hover:bg-primary-hover disabled:opacity-50">
            찾기
          </button>
        </form>

        {res && (
          <p className="mt-3 text-xs text-text-secondary">
            &quot;{res.query}&quot; — {total ? `${total}건` : "찾은 것이 없습니다"}
          </p>
        )}
        <div className="mt-3 flex flex-col gap-5">
          {res?.groups.map((g) => {
            const Icon = ICON[g.kind];
            return (
              <div key={g.kind}>
                <h2 className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
                  <Icon className="size-4 text-primary" aria-hidden />
                  {g.label} <span className="font-normal text-text-secondary">{g.items.length}</span>
                </h2>
                <div className="mt-1.5 flex flex-col gap-1">
                  {g.items.map((it, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => open(it)}
                      className={cn("cursor-pointer rounded-lg border border-transparent px-3 py-2 text-left hover:border-neutral-200 hover:bg-neutral-50", view && it.docId === view.docId && it.chunk === view.chunk && "border-primary-soft-border bg-primary-soft")}
                    >
                      <span className="block truncate text-sm text-text-primary">{it.title}</span>
                      {it.text && <span className="mt-0.5 line-clamp-2 block text-xs leading-5 text-text-secondary">{it.text}</span>}
                      {(it.sub || it.at) && <span className="mt-0.5 block text-[11px] text-text-secondary">{[it.sub, when(it.at)].filter(Boolean).join(" · ")}</span>}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>
      <section className="flex w-[44%] min-w-[360px] shrink-0 flex-col border-l border-neutral-200">
        {tableOpen ? (
          <AssetDrawer key={tableOpen} id={tableOpen} taskId={null} onClose={() => setTableOpen(null)} onChanged={() => undefined} onRemoved={() => setTableOpen(null)} className="w-full border-l-0" />
        ) : viewDoc && view ? (
          <DocViewerBody workspaceId={ws.workspaceId} doc={viewDoc} focusChunk={view.chunk ?? undefined} focusCell={view.cell} tick={view.tick} />
        ) : (
          <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-text-secondary">자료 문단·원장·데이터 파일을 누르면 원문이 여기 열립니다.</div>
        )}
      </section>
    </div>
  );
}
