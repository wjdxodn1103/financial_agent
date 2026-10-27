"use client";

/**
 * 데이터 설정 — 이 작업에서 AI 가 쓰는 데이터. 묶음(워크스페이스·사내·개인) 켜고 끄기 + 데이터를 찾아 추가.
 * 기본 = 워크스페이스·사내. 묶음을 다 끄고 데이터만 고르면 그 데이터로만 작업한다. (BE drive.report_scope_ids·scope_view)
 */
import { useEffect, useState } from "react";
import { useAtom, useAtomValue } from "jotai";
import { Check, FileText, Loader2, Plus, Search, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { searchDrive } from "../../../workspace/api";
import { useWorkspace } from "../../../workspace/context";
import type { DriveSearch } from "../../../workspace/types";
import { dataScopeAtom, dataSettingsOpenAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import type { DataGroup } from "../../types";

export const GROUP_LABEL: Record<DataGroup, string> = { workspace: "워크스페이스 데이터", company: "사내 데이터", personal: "개인 데이터" };
export const GROUPS: DataGroup[] = ["workspace", "company", "personal"];
export const DEFAULT_GROUPS: Record<DataGroup, boolean> = { workspace: true, company: true, personal: false };

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn("flex h-9 cursor-pointer items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold transition-colors", on ? "bg-primary text-white hover:bg-primary-hover" : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200")}
    >
      {on && <Check className="size-3.5" aria-hidden />}
      {children}
    </button>
  );
}

export function DataSettingsDialog() {
  const [open, setOpen] = useAtom(dataSettingsOpenAtom);
  if (!open) return null;
  return <Body onClose={() => setOpen(false)} />;
}

function Body({ onClose }: { onClose: () => void }) {
  const ws = useWorkspace();
  const actions = useReportActions();
  const scope = useAtomValue(dataScopeAtom);
  const [groups, setGroups] = useState<Record<DataGroup, boolean>>(scope?.groups ?? DEFAULT_GROUPS);
  const [docs, setDocs] = useState<{ id: string; label: string }[]>(scope?.docs ?? []);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<DriveSearch | null>(null);
  const [busy, setBusy] = useState(false);
  const counts = scope?.counts;
  const all = GROUPS.every((g) => groups[g]);
  const picked = new Set(docs.map((d) => d.id));

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      searchDrive(ws.workspaceId, q)
        .then((r) => !cancelled && setFound(r))
        .catch(() => !cancelled && setFound({ folders: [], data: [] }));
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [q, ws.workspaceId]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const apply = async () => {
    setBusy(true);
    const ok = await actions.setDataScope({ groups, docIds: docs.map((d) => d.id), folderIds: (scope?.folders ?? []).map((f) => f.id) });
    setBusy(false);
    if (ok) onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={() => !busy && onClose()}>
      <div onMouseDown={(e) => e.stopPropagation()} className="flex max-h-[86vh] w-full max-w-[600px] flex-col overflow-hidden rounded-[24px] bg-white shadow-xl">
        <div className="flex items-start gap-3 px-6 pt-6">
          <div className="min-w-0 flex-1">
            <h2 className="text-[20px] font-bold tracking-tight text-text-primary">데이터 설정</h2>
            <p className="mt-1 text-[13px] text-text-secondary">필요한 데이터만 선택하면 AI가 더 빠르고 정확하게 작업을 진행할 수 있습니다.</p>
          </div>
          <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>

        <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-6 pt-4 pb-2">
          <div className="flex flex-wrap gap-1.5">
            <Toggle on={all} onClick={() => setGroups(all ? { workspace: false, company: false, personal: false } : { workspace: true, company: true, personal: true })}>
              모든 데이터
            </Toggle>
            {GROUPS.map((g) => (
              <Toggle key={g} on={groups[g]} onClick={() => setGroups((cur) => ({ ...cur, [g]: !cur[g] }))}>
                {GROUP_LABEL[g]}
                {counts && <span className={cn("tabular-nums", groups[g] ? "text-white/80" : "text-neutral-400")}>{counts[g]}</span>}
              </Toggle>
            ))}
          </div>

          {docs.length > 0 && (
            <div className="mt-4">
              <p className="text-[13px] font-semibold text-neutral-600">추가한 데이터</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {docs.map((d) => (
                  <span key={d.id} className="inline-flex items-center gap-1 rounded-lg bg-primary-soft py-1 pr-1 pl-2 text-[13px] font-medium text-primary-soft-foreground">
                    <FileText className="size-3.5" aria-hidden />
                    <span className="max-w-[240px] truncate">{d.label}</span>
                    <button type="button" aria-label={`${d.label} 빼기`} onClick={() => setDocs((cur) => cur.filter((x) => x.id !== d.id))} className="cursor-pointer rounded p-0.5 hover:bg-white/60">
                      <X className="size-3.5" aria-hidden />
                    </button>
                  </span>
                ))}
              </div>
            </div>
          )}

          <p className="mt-5 text-[13px] font-semibold text-neutral-600">데이터 추가</p>
          <label className="mt-2 flex h-11 items-center gap-2 rounded-xl bg-neutral-100 px-3.5 focus-within:bg-white focus-within:ring-2 focus-within:ring-primary/30">
            <Search className="size-4 text-neutral-500" aria-hidden />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="데이터 이름으로 찾기" className="min-w-0 flex-1 bg-transparent text-[14px] outline-none" />
          </label>
          <div className="mt-1 pb-2">
            {found?.data.map((d) => (
              <button
                key={d.id}
                type="button"
                disabled={picked.has(d.id)}
                onClick={() => setDocs((cur) => [...cur, { id: d.id, label: d.label }])}
                className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-neutral-50 disabled:cursor-default disabled:opacity-40"
              >
                <FileText className="size-[18px] shrink-0 text-neutral-500" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] text-text-primary">{d.label}</span>
                  <span className="block truncate text-[12px] text-neutral-500">{d.shared ? "사내 데이터" : d.personal ? "개인 데이터" : ["워크스페이스 데이터", d.path].filter(Boolean).join(" · ")}</span>
                </span>
                {!picked.has(d.id) && <Plus className="size-4 shrink-0 text-primary" aria-hidden />}
              </button>
            ))}
            {found && !found.data.length && <p className="px-2.5 py-3 text-[14px] text-neutral-500">찾은 데이터가 없어요</p>}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-neutral-100 px-6 py-4">
          {!GROUPS.some((g) => groups[g]) && !docs.length && <p className="mr-auto text-[13px] text-text-secondary">고른 데이터가 없으면 AI는 데이터 없이 답합니다.</p>}
          <button type="button" onClick={onClose} className="h-10 cursor-pointer rounded-xl bg-neutral-100 px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-200">
            취소
          </button>
          <button type="button" disabled={busy} onClick={() => void apply()} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
            적용
          </button>
        </div>
      </div>
    </div>
  );
}
