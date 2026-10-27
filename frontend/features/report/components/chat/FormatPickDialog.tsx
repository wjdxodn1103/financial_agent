"use client";

/**
 * 문서 작성 시작 — 양식 고르기. 문서 작성을 처음 켤 때(아직 양식·섹션이 없을 때)와 시작 카드 '문서 쓰기 시작'에서 뜬다.
 * 고르면 그 양식의 섹션이 깔리고 문서 작성 모드가 켜진다. 양식은 중간에 바꾸지 않는다(양식 메뉴에서 관리).
 */
import { useState } from "react";
import { useAtom } from "jotai";
import { Check, FileText, Loader2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useWorkspace } from "../../../workspace/context";
import { formatPickAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import type { ReportTypeInfo } from "../../types";

const GROUPS: { id: string; label: string; test: (t: ReportTypeInfo) => boolean }[] = [
  { id: "company", label: "사내", test: (t) => t.kind !== "registered" || t.scope === "company" },
  { id: "workspace", label: "워크스페이스", test: (t) => t.kind === "registered" && (t.scope === "workspace" || t.scope === "user") },
];

export function FormatPickDialog() {
  const [open, setOpen] = useAtom(formatPickAtom);
  const ws = useWorkspace();
  const actions = useReportActions();
  const formats = ws.meta.reportTypes.filter((t) => t.kind !== "free");
  const [pick, setPick] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  if (!open) return null;

  const close = () => {
    setOpen(false);
    setPick(null);
    setTitle("");
  };
  const start = async (id: string | null) => {
    setBusy(true);
    try {
      if (id && !(await actions.setReportType(id))) return;
      if (title.trim()) await actions.setSetup({ title: title.trim() });
      actions.setModes({ research: false, writing: true });
      close();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={() => !busy && close()}>
      <div onMouseDown={(e) => e.stopPropagation()} className="flex max-h-[86vh] w-full max-w-[600px] flex-col overflow-hidden rounded-[24px] bg-white shadow-xl">
        <div className="flex items-start gap-3 px-6 pt-6">
          <h2 className="flex-1 text-[20px] font-bold tracking-tight text-text-primary">어떤 양식으로 쓸까요?</h2>
          <button type="button" aria-label="닫기" onClick={close} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        <div className="thin-scrollbar mt-3 min-h-0 flex-1 overflow-y-auto px-4">
          {GROUPS.map((g) => {
            const rows = formats.filter(g.test);
            if (!rows.length) return null;
            return (
              <div key={g.id} className="mb-2">
                <p className="px-2 py-1.5 text-[12px] font-semibold text-neutral-500">{g.label}</p>
                {rows.map((t) => {
                  const on = pick === t.id;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => setPick(t.id)}
                      onDoubleClick={() => void start(t.id)}
                      className={cn("flex w-full cursor-pointer items-center gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors", on ? "bg-primary-soft" : "hover:bg-neutral-50")}
                    >
                      <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-xl", on ? "bg-primary text-white" : "bg-neutral-100 text-neutral-500")}>
                        {on ? <Check className="size-4" aria-hidden /> : <FileText className="size-4" aria-hidden />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] font-semibold text-text-primary">{t.title}</span>
                        <span className="block truncate text-[12px] text-text-secondary">
                          {[`섹션 ${t.items.length}`, t.tables ? `표 ${t.tables}` : null, t.charts ? `차트 ${t.charts}` : null, t.desc].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
        <div className="border-t border-neutral-100 px-6 py-4">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="문서 제목(선택)" aria-label="문서 제목" className="h-10 w-full rounded-xl bg-neutral-100 px-3.5 text-[14px] outline-none focus:bg-white focus:ring-2 focus:ring-primary/30" />
          <div className="mt-3 flex justify-end gap-2">
            <button type="button" disabled={busy} onClick={() => void start(null)} className="h-10 cursor-pointer rounded-xl bg-neutral-100 px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-200 disabled:opacity-50">
              양식 없이
            </button>
            <button type="button" disabled={busy || !pick} onClick={() => void start(pick)} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40">
              {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}이 양식으로 시작
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
