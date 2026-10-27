"use client";

/** 새 문서 — 양식 고르기 · 제목 · 드라이브 위치 · 참고 데이터(워크스페이스 기본값 / 직접 고르기). 만들면 작성 화면으로 연다. */
import { useEffect, useMemo, useState } from "react";
import { FileText, LayoutTemplate, Loader2, Search, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError } from "../../report/api";
import { createReport, getDrive } from "../api";
import { useWorkspace } from "../context";
import { DataScopePicker, DEFAULT_SCOPE, toScope, type ScopeChoice } from "./DataScopePicker";

export function NewDocumentDialog({ folderId = null, onClose }: { folderId?: string | null; onClose: () => void }) {
  const ws = useWorkspace();
  const types = useMemo(() => ws.meta.reportTypes.filter((t) => t.kind !== "free"), [ws.meta.reportTypes]);
  const [q, setQ] = useState("");
  const [type, setType] = useState(types.find((t) => t.kind === "format")?.id ?? types[0]?.id ?? "");
  const [title, setTitle] = useState("");
  const [folder, setFolder] = useState<string | null>(folderId);
  const [tree, setTree] = useState<{ id: string; name: string; parentId: string | null }[]>([]);
  const [scope, setScope] = useState<ScopeChoice>(DEFAULT_SCOPE);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void getDrive(ws.workspaceId)
      .then((d) => setTree(d.tree))
      .catch(() => setTree([]));
  }, [ws.workspaceId]);

  const shown = useMemo(() => {
    const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return types.filter((t) => words.every((w) => [t.title, t.desc, ...(t.tags ?? [])].join(" ").toLowerCase().includes(w)));
  }, [q, types]);

  const pathOf = (id: string): string => {
    const parts: string[] = [];
    let cur = tree.find((f) => f.id === id);
    while (cur && parts.length < 20) {
      parts.unshift(cur.name);
      cur = tree.find((f) => f.id === cur!.parentId);
    }
    return parts.join(" / ");
  };

  const create = async () => {
    if (!type || busy) return;
    setBusy(true);
    try {
      const p = await createReport(ws.workspaceId, { reportType: type, title: title.trim(), folderId: folder, dataScope: toScope(scope) });
      onClose();
      ws.nav.openReport(p.session.id);
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "만들지 못했습니다.", { position: "top-center" });
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="thin-scrollbar flex max-h-[90vh] w-full max-w-[640px] flex-col overflow-y-auto rounded-[24px] bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between">
          <h2 className="text-[22px] font-bold tracking-tight text-text-primary">새 문서</h2>
          <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>

        <section className="mt-5">
          <p className="text-[15px] font-bold text-text-primary">양식</p>
          <label className="mt-2 flex h-10 items-center gap-2 rounded-xl bg-neutral-100 px-3.5 focus-within:bg-white focus-within:ring-2 focus-within:ring-primary/30">
            <Search className="size-4 text-neutral-500" aria-hidden />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="양식 찾기" className="min-w-0 flex-1 bg-transparent text-[14px] outline-none" />
          </label>
          <div className="thin-scrollbar mt-2 grid max-h-[220px] gap-1.5 overflow-y-auto sm:grid-cols-2">
            {shown.map((t) => {
              const Icon = t.kind === "format" || t.kind === "registered" ? LayoutTemplate : FileText;
              return (
                <button key={t.id} type="button" title={t.desc} onClick={() => setType(t.id)} className={cn("flex cursor-pointer items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition-colors", type === t.id ? "bg-primary-soft ring-2 ring-primary/40" : "bg-neutral-50 hover:bg-neutral-100")}>
                  <Icon className={cn("size-[18px] shrink-0", type === t.id ? "text-primary" : "text-neutral-500")} aria-hidden />
                  <span className="min-w-0">
                    <span className="block truncate text-[14px] font-semibold text-text-primary">{t.title}</span>
                    <span className="block truncate text-[12px] text-neutral-500">{t.kind === "format" || t.kind === "registered" ? `${t.kind === "registered" ? "등록 양식 · " : ""}섹션 ${t.items.length} · 표 ${t.tables ?? 0} · ${t.kind === "registered" ? "차트" : "그림"} ${t.charts ?? 0}` : `섹션 ${t.items.length}`}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="mt-5 grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-[15px] font-bold text-text-primary">제목</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="제목 없음" className="mt-2 h-10 w-full rounded-xl bg-neutral-100 px-3.5 text-[14px] outline-none focus:bg-white focus:ring-2 focus:ring-primary/30" />
          </label>
          <label className="block">
            <span className="text-[15px] font-bold text-text-primary">위치</span>
            <select value={folder ?? ""} onChange={(e) => setFolder(e.target.value || null)} className="mt-2 h-10 w-full rounded-xl bg-neutral-100 px-3 text-[14px] outline-none">
              <option value="">드라이브</option>
              {tree.map((f) => (
                <option key={f.id} value={f.id}>
                  {pathOf(f.id)}
                </option>
              ))}
            </select>
          </label>
        </section>

        <section className="mt-5">
          <p className="mb-2 text-[15px] font-bold text-text-primary">참고 데이터</p>
          <DataScopePicker value={scope} onChange={setScope} />
        </section>

        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="h-11 cursor-pointer rounded-xl bg-neutral-100 px-5 text-[15px] font-semibold text-neutral-700 hover:bg-neutral-200">
            취소
          </button>
          <button type="button" disabled={!type || busy || (scope.mode === "custom" && !scope.docs.length && !scope.folders.length)} onClick={() => void create()} className="flex h-11 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-5 text-[15px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40">
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
            만들기
          </button>
        </div>
      </div>
    </div>
  );
}
