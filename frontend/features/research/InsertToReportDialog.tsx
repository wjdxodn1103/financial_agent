"use client";

/**
 * 문서에 넣기 — 내 문서(리포트)와 섹션을 고르면 그 섹션 뒤에 지금 표의 복사본이 들어간다(표를 나중에 고쳐도 문서는 그대로).
 */
import { useEffect, useState } from "react";
import { FileText, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError, getSession } from "../report/api";
import type { ReportSection, SessionListItem } from "../report/types";
import { listReports } from "../workspace/api";
import { useWorkspace } from "../workspace/context";
import { insertTable } from "./api";
import type { ResearchTable } from "./types";

export function InsertToReportDialog({ table, onClose }: { table: ResearchTable; onClose: () => void }) {
  const ws = useWorkspace();
  const [reports, setReports] = useState<SessionListItem[] | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [sections, setSections] = useState<ReportSection[] | null>(null);
  const [step, setStep] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void listReports(ws.workspaceId)
      .then((xs) => setReports(xs.filter((r) => r.createdBy === ws.me.id)))
      .catch(() => setReports([]));
  }, [ws.workspaceId, ws.me.id]);

  useEffect(() => {
    setSections(null);
    setStep(null);
    if (!report) return;
    let cancelled = false;
    void getSession(report)
      .then((p) => !cancelled && setSections(p.session.sections))
      .catch(() => !cancelled && setSections([]));
    return () => {
      cancelled = true;
    };
  }, [report]);

  const save = async () => {
    if (!report || !step) return;
    setBusy(true);
    try {
      await insertTable(report, table.id, step);
      const id = report;
      toast.success("문서에 넣었습니다.", {
        position: "top-center",
        action: { label: "열기", onClick: () => ws.nav.openReport(id) },
      });
      onClose();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "넣지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  const row = (on: boolean) =>
    cn("flex w-full cursor-pointer items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-[14px] transition-colors", on ? "bg-primary-soft font-semibold text-primary" : "text-text-primary hover:bg-neutral-50");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="w-full max-w-[560px] rounded-[24px] bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <h2 className="flex-1 text-[20px] font-bold tracking-tight text-text-primary">문서에 넣기</h2>
          <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div>
            <p className="mb-1.5 text-[13px] font-semibold text-neutral-600">문서</p>
            <div className="thin-scrollbar flex max-h-[300px] flex-col gap-0.5 overflow-y-auto">
              {reports === null && <p className="px-3 py-2 text-[13px] text-text-secondary">불러오는 중…</p>}
              {reports?.length === 0 && <p className="px-3 py-2 text-[13px] text-text-secondary">내 문서가 없습니다</p>}
              {reports?.map((r) => (
                <button key={r.id} type="button" onClick={() => setReport(r.id)} className={row(report === r.id)}>
                  <FileText className="size-4 shrink-0" aria-hidden />
                  <span className="truncate">{r.title}</span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1.5 text-[13px] font-semibold text-neutral-600">섹션 뒤에</p>
            <div className="thin-scrollbar flex max-h-[300px] flex-col gap-0.5 overflow-y-auto">
              {report && sections === null && <p className="px-3 py-2 text-[13px] text-text-secondary">불러오는 중…</p>}
              {sections?.map((s) => (
                <button key={s.step} type="button" onClick={() => setStep(s.step)} className={row(step === s.step)}>
                  <span className="truncate">{s.title}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="h-10 cursor-pointer rounded-xl bg-neutral-100 px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-200">
            취소
          </button>
          <button
            type="button"
            disabled={busy || !report || !step}
            onClick={() => void save()}
            className="h-10 cursor-pointer rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40"
          >
            넣기
          </button>
        </div>
      </div>
    </div>
  );
}
