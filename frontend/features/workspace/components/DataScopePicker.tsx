"use client";

/**
 * 참고 데이터 고르기 — 워크스페이스 기본값(사내 공용 + 워크스페이스 데이터 전부) 또는 직접 고르기(데이터·폴더를 찾아 추가).
 * 새 문서 창과 작업 채팅의 데이터 탭이 같이 쓴다. 폴더를 고르면 그 안(하위 폴더 포함)의 데이터가 들어가고, 나중에 들어온 데이터도 따라간다.
 */
import { useEffect, useState } from "react";
import { FileText, Folder, Plus, Search, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { searchDrive } from "../api";
import { useWorkspace } from "../context";
import type { DriveSearch } from "../types";

export interface ScopeChoice {
  mode: "default" | "custom";
  docs: { id: string; label: string }[];
  folders: { id: string; name: string }[];
}

export function DataScopePicker({ value, onChange }: { value: ScopeChoice; onChange: (v: ScopeChoice) => void }) {
  const ws = useWorkspace();
  const [q, setQ] = useState("");
  const [found, setFound] = useState<DriveSearch | null>(null);

  useEffect(() => {
    if (value.mode !== "custom") return;
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
  }, [q, value.mode, ws.workspaceId]);

  const pickedDocs = new Set(value.docs.map((d) => d.id));
  const pickedFolders = new Set(value.folders.map((f) => f.id));
  const count = value.docs.length + value.folders.length;

  return (
    <div>
      <div className="flex rounded-xl bg-neutral-100 p-1 text-[14px] font-semibold">
        {(
          [
            ["default", "워크스페이스 기본값"],
            ["custom", "직접 고르기"],
          ] as const
        ).map(([id, label]) => (
          <button key={id} type="button" onClick={() => onChange({ ...value, mode: id })} className={cn("flex-1 cursor-pointer rounded-lg px-3 py-2 transition-colors", value.mode === id ? "bg-white text-text-primary shadow-sm" : "text-neutral-500 hover:text-neutral-700")}>
            {label}
          </button>
        ))}
      </div>

      {value.mode === "custom" && (
        <div className="mt-3">
          {count > 0 && (
            <div className="mb-2.5 flex flex-wrap gap-1.5">
              {value.folders.map((f) => (
                <span key={f.id} className="inline-flex items-center gap-1 rounded-lg bg-primary-soft py-1 pr-1 pl-2 text-[13px] font-medium text-primary-soft-foreground">
                  <Folder className="size-3.5" aria-hidden />
                  {f.name}
                  <button type="button" aria-label={`${f.name} 빼기`} onClick={() => onChange({ ...value, folders: value.folders.filter((x) => x.id !== f.id) })} className="cursor-pointer rounded p-0.5 hover:bg-white/60">
                    <X className="size-3.5" aria-hidden />
                  </button>
                </span>
              ))}
              {value.docs.map((d) => (
                <span key={d.id} className="inline-flex items-center gap-1 rounded-lg bg-neutral-100 py-1 pr-1 pl-2 text-[13px] font-medium text-text-primary">
                  <FileText className="size-3.5 text-neutral-500" aria-hidden />
                  <span className="max-w-[220px] truncate">{d.label}</span>
                  <button type="button" aria-label={`${d.label} 빼기`} onClick={() => onChange({ ...value, docs: value.docs.filter((x) => x.id !== d.id) })} className="cursor-pointer rounded p-0.5 hover:bg-neutral-200">
                    <X className="size-3.5" aria-hidden />
                  </button>
                </span>
              ))}
            </div>
          )}
          <label className="flex h-11 items-center gap-2 rounded-xl bg-neutral-100 px-3.5 focus-within:bg-white focus-within:ring-2 focus-within:ring-primary/30">
            <Search className="size-4 text-neutral-500" aria-hidden />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="데이터·폴더 찾기" className="min-w-0 flex-1 bg-transparent text-[14px] outline-none" />
          </label>
          <div className="thin-scrollbar mt-2 max-h-[220px] overflow-y-auto">
            {found?.folders.map((f) => (
              <button
                key={f.id}
                type="button"
                disabled={pickedFolders.has(f.id)}
                onClick={() => onChange({ ...value, folders: [...value.folders, { id: f.id, name: f.name }] })}
                className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-neutral-50 disabled:cursor-default disabled:opacity-40"
              >
                <Folder className="size-[18px] shrink-0 fill-amber-300 text-amber-400" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] text-text-primary">{f.name}</span>
                  <span className="block truncate text-[12px] text-neutral-500">{[f.path, `데이터 ${f.items}`].filter(Boolean).join(" · ")}</span>
                </span>
                {!pickedFolders.has(f.id) && <Plus className="size-4 shrink-0 text-primary" aria-hidden />}
              </button>
            ))}
            {found?.data.map((d) => (
              <button
                key={d.id}
                type="button"
                disabled={pickedDocs.has(d.id)}
                onClick={() => onChange({ ...value, docs: [...value.docs, { id: d.id, label: d.label }] })}
                className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-neutral-50 disabled:cursor-default disabled:opacity-40"
              >
                <FileText className="size-[18px] shrink-0 text-neutral-500" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] text-text-primary">{d.label}</span>
                  {d.path && <span className="block truncate text-[12px] text-neutral-500">{d.path}</span>}
                </span>
                {!pickedDocs.has(d.id) && <Plus className="size-4 shrink-0 text-primary" aria-hidden />}
              </button>
            ))}
            {found && !found.folders.length && !found.data.length && <p className="px-2.5 py-3 text-[14px] text-neutral-500">찾은 것이 없어요</p>}
          </div>
        </div>
      )}
    </div>
  );
}

export const DEFAULT_SCOPE: ScopeChoice = { mode: "default", docs: [], folders: [] };

export function toScope(v: ScopeChoice) {
  return v.mode === "custom" ? { mode: "custom" as const, docIds: v.docs.map((d) => d.id), folderIds: v.folders.map((f) => f.id) } : { mode: "default" as const };
}
