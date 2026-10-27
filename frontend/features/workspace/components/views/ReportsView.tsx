"use client";

/**
 * AI 작업 — 작업을 고르면 작업 화면(대화 | 문서 | 데이터). 고른 작업이 없으면 빈 작업을 연다(아무것도 안 한 내 작업이 있으면 그것,
 * 없으면 새로 — 'AI 작업'이 곧 새 작업). 다른 작업은 작업 화면의 '작업 불러오기'로 연다.
 * 아래 목록 화면(내 작업·새 작업·새 문서)은 작업을 만들 수 없는 열람자에게만 보인다. 대화는 개인이라 목록은 내 것만.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { FilePlus2, FileText, MessageSquare, Plus } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { Studio } from "../../../report/components/studio/Studio";
import { ReportStudioProvider } from "../../../report/hooks/useReportStudio";
import { NavContext, type AppNav } from "../../../report/nav";
import type { ReportTypeId, SessionListItem } from "../../../report/types";
import { createReport, listReports } from "../../api";
import { useWorkspace } from "../../context";
import { NewDocumentDialog } from "../NewDocumentDialog";

export function ReportsView({ reportId, tableId = null }: { reportId: string | null; tableId?: string | null }) {
  const ws = useWorkspace();
  const [items, setItems] = useState<SessionListItem[] | null>(null);
  const [newDoc, setNewDoc] = useState(false);

  // 새 작업 = 양식 없음(free) — 문서 작성을 켜면 그때 양식을 붙인다
  const create = useCallback(
    async (reportType?: ReportTypeId) => {
      try {
        const p = await createReport(ws.workspaceId, { reportType: reportType ?? "free" });
        ws.nav.openReport(p.session.id);
      } catch {
        toast.error("새 작업을 만들지 못했습니다.", { position: "top-center" });
      }
    },
    [ws.nav, ws.workspaceId],
  );

  const nav = useMemo<AppNav>(() => ({ open: (id) => ws.nav.openReport(id), create, back: () => ws.nav.openReport(null) }), [create, ws.nav]);

  const editor = ws.can("editor");
  useEffect(() => {
    if (reportId) return;
    let cancelled = false;
    listReports(ws.workspaceId)
      .then(async (x) => {
        const mine = x.filter((r) => r.createdBy === ws.me.id);
        if (cancelled) return;
        if (!editor) return void setItems(mine);
        // 빈 작업 열기 — 기록에 목록 화면을 남기지 않는다(뒤로 가기가 다시 여기로 오지 않게)
        const empty = mine.find((r) => r.empty);
        const id = empty?.id ?? (await createReport(ws.workspaceId, { reportType: "free" })).session.id;
        if (!cancelled) ws.nav.openReport(id, null, true);
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        if (editor) toast.error("새 작업을 열지 못했습니다.", { position: "top-center" });
      });
    return () => {
      cancelled = true;
    };
  }, [editor, reportId, ws.nav, ws.workspaceId, ws.me.id]);

  if (reportId) {
    return (
      <NavContext.Provider value={nav}>
        <ReportStudioProvider key={reportId} sessionId={reportId} initialTableId={tableId}>
          <Studio />
        </ReportStudioProvider>
      </NavContext.Provider>
    );
  }

  if (editor) return <div className="flex flex-1 items-center justify-center text-sm text-text-secondary">불러오는 중…</div>;

  const typeTitle = (id: string) => ws.meta.reportTypes.find((t) => t.id === id)?.title ?? id;

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
      <div className="mx-auto max-w-[1040px] px-8 pt-8 pb-14">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-[26px] leading-tight font-bold tracking-tight text-text-primary">AI 작업</h1>
          {ws.can("editor") && (
            <span className="flex gap-2">
              <button type="button" onClick={() => setNewDoc(true)} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-neutral-200 px-4 text-[14px] font-semibold text-neutral-800 hover:bg-neutral-300">
                <FilePlus2 className="size-4" aria-hidden />새 문서
              </button>
              <button type="button" onClick={() => void create()} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover">
                <Plus className="size-4" aria-hidden />새 작업
              </button>
            </span>
          )}
        </div>
        <section className="mt-6 rounded-[24px] bg-white px-4 py-3">
          {items === null && <p className="px-2 py-6 text-[15px] text-neutral-500">불러오는 중…</p>}
          {items?.length === 0 && <p className="px-2 py-10 text-center text-[15px] text-neutral-500">아직 작업이 없어요</p>}
          {items?.map((r) => {
            const pct = r.sections ? Math.round((r.written / r.sections) * 100) : 0;
            const doc = r.hasDoc !== false;
            return (
              <button key={r.id} type="button" onClick={() => ws.nav.openReport(r.id)} className="flex w-full cursor-pointer items-center gap-3.5 rounded-xl px-2 py-3 text-left transition-colors hover:bg-neutral-50">
                <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl", doc ? "bg-primary-soft text-primary" : "bg-neutral-100 text-neutral-500")}>
                  {doc ? <FileText className="size-[18px]" aria-hidden /> : <MessageSquare className="size-[18px]" aria-hidden />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[15px] font-semibold text-text-primary">{r.title || "새 작업"}</span>
                  <span className="block truncate text-[13px] text-neutral-500">{doc ? typeTitle(r.reportType) : "대화"}</span>
                </span>
                <span className={cn("flex shrink-0 items-center gap-2", !doc && "hidden")}>
                  <span className="h-1.5 w-24 overflow-hidden rounded-full bg-neutral-100">
                    <span className="block h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                  </span>
                  <span className="num w-10 text-right text-[12px] font-semibold text-neutral-500">
                    {r.written}/{r.sections}
                  </span>
                </span>
              </button>
            );
          })}
        </section>
      </div>
      {newDoc && <NewDocumentDialog onClose={() => setNewDoc(false)} />}
    </div>
  );
}
