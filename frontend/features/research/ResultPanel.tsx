"use client";

/**
 * AI 채팅 오른쪽 결과 패널 — [결과] 만든 표(칸을 누르면 원문) · [문서 보기] 원문.
 * 표 버튼: 양식으로 저장 · 드라이브에 저장 · 행/열 바꾸기(만든 사람만) · 문서에 넣기(편집자 이상) · 내려받기(DOCX·XLSX).
 * 남이 저장한 표(드라이브에서 연 것)는 넣기·내려받기만.
 */
import { useState } from "react";
import { ArrowLeftRight, Download, FilePlus2, FolderCheck, FolderPlus, LayoutTemplate, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError, downloadFile } from "../report/api";
import { AssetBlockView } from "../report/components/report/FormatBlock";
import { DocViewerBody } from "../report/components/viewer/DocViewerBody";
import { useWorkspace } from "../workspace/context";
import { patchTable, tableExportPath } from "./api";
import { InsertToReportDialog } from "./InsertToReportDialog";
import { TemplateDialog } from "./TemplateDialog";
import type { useResearch } from "./useResearch";

type Research = ReturnType<typeof useResearch>;

const btn = "flex h-9 cursor-pointer items-center gap-1.5 rounded-xl bg-neutral-100 px-3 text-[13px] font-semibold text-neutral-700 transition-colors hover:bg-neutral-200 disabled:cursor-default disabled:opacity-50";

export function ResultPanel({ r }: { r: Research }) {
  const ws = useWorkspace();
  const t = r.active;
  const [saving, setSaving] = useState(false);
  const [templating, setTemplating] = useState(false);
  const [inserting, setInserting] = useState(false);
  const [menu, setMenu] = useState(false);
  const doc = r.viewing ? r.docs[r.viewing.docId] : undefined;
  const items = t ? t.items.filter((i) => !i.hidden).length : 0;

  const run = async (fn: () => Promise<unknown>, fail: string) => {
    setSaving(true);
    try {
      await fn();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : fail, {
        position: "top-center",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside className="flex w-[min(620px,52%)] shrink-0 flex-col border-l border-neutral-200 bg-white">
      <div className="flex items-center gap-1 border-b border-neutral-100 px-4 pt-3 pb-2">
        {(
          [
            ["result", "결과"],
            ["viewer", "문서 보기"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => r.setTab(id)}
            className={cn("cursor-pointer rounded-lg px-3 py-1.5 text-[14px] font-semibold transition-colors", r.tab === id ? "bg-neutral-100 text-text-primary" : "text-neutral-500 hover:text-neutral-700")}
          >
            {label}
          </button>
        ))}
      </div>

      {r.tab === "viewer" ? (
        <div className="min-h-0 flex-1">
          {doc && r.viewing ? (
            <DocViewerBody workspaceId={ws.workspaceId} doc={doc} focusChunk={r.viewing.chunk} focusCell={r.viewing.cell ?? null} tick={r.viewing.tick} />
          ) : (
            <p className="px-6 py-10 text-center text-[13px] text-text-secondary">칸이나 출처를 누르면 원문이 열립니다</p>
          )}
        </div>
      ) : (
        <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-5 pt-4 pb-8">
          {r.tables.length > 1 && (
            <div className="mb-4 flex flex-wrap gap-1.5">
              {r.tables.map((x) => (
                <button
                  key={x.id}
                  type="button"
                  onClick={() => r.setActiveId(x.id)}
                  className={cn(
                    "max-w-[220px] cursor-pointer truncate rounded-full px-3 py-1 text-[12px] font-medium transition-colors",
                    x.id === t?.id ? "bg-primary-soft text-primary" : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200",
                  )}
                >
                  {x.title}
                </button>
              ))}
            </div>
          )}
          {t && (
            <>
              <h2 className="text-[18px] leading-snug font-bold tracking-tight text-text-primary">{t.title}</h2>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 text-[12px] text-text-secondary">
                {t.period && <span>{t.period.label} 기준</span>}
                <span>
                  {t.subjects.length}행 × {items}열
                </span>
                {!t.mine && <span>{t.createdBy}</span>}
                {t.status === "running" && (
                  <span className="flex items-center gap-1 text-primary">
                    <Loader2 className="size-3 animate-spin" aria-hidden />
                    {t.progress.done ?? 0}/{t.progress.total ?? t.subjects.length}
                  </span>
                )}
              </p>
              {
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {ws.can("editor") && (
                    <button type="button" disabled={t.status !== "done"} onClick={() => setInserting(true)} className={btn}>
                      <FilePlus2 className="size-4" aria-hidden />
                      문서에 넣기
                    </button>
                  )}
                  {t.mine && (
                    <button type="button" disabled={t.status === "running"} onClick={() => setTemplating(true)} className={btn}>
                      <LayoutTemplate className="size-4" aria-hidden />
                      양식으로 저장
                    </button>
                  )}
                  {t.mine && (
                    <button
                      type="button"
                      disabled={saving || t.saved || t.status === "running"}
                      onClick={() =>
                        void run(async () => {
                          r.replaceTable(await patchTable(t.id, { saved: true }));
                          toast.success("드라이브에 저장했습니다.", {
                            position: "top-center",
                          });
                        }, "저장하지 못했습니다.")
                      }
                      className={btn}
                    >
                      {t.saved ? <FolderCheck className="size-4 text-primary" aria-hidden /> : <FolderPlus className="size-4" aria-hidden />}
                      {t.saved ? "드라이브에 있음" : "드라이브에 저장"}
                    </button>
                  )}
                  <div className="relative">
                    <button type="button" title="내려받기" aria-label="내려받기" disabled={t.status !== "done"} onClick={() => setMenu((v) => !v)} className={btn}>
                      <Download className="size-4" aria-hidden />
                    </button>
                    {menu && (
                      <div className="absolute top-full right-0 z-30 mt-1 w-36 rounded-2xl bg-white p-1.5 shadow-[0_8px_24px_rgba(0,27,55,0.14)]" onMouseLeave={() => setMenu(false)}>
                        {(["docx", "xlsx"] as const).map((fmt) => (
                          <button
                            key={fmt}
                            type="button"
                            onClick={() => (setMenu(false), void run(() => downloadFile(tableExportPath(t.id, fmt), `${t.title}.${fmt}`), "내려받지 못했습니다."))}
                            className="flex w-full cursor-pointer items-center rounded-xl px-3 py-2 text-left text-[14px] font-medium text-text-primary hover:bg-neutral-100"
                          >
                            {fmt === "docx" ? "Word (DOCX)" : "Excel (XLSX)"}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  {t.mine && (
                    <button
                      type="button"
                      title="행·열 바꾸기"
                      aria-label="행·열 바꾸기"
                      disabled={saving}
                      onClick={() =>
                        void run(
                          async () =>
                            r.replaceTable(
                              await patchTable(t.id, {
                                orientation: t.spec.orientation === "items_as_rows" ? "subjects_as_rows" : "items_as_rows",
                              }),
                            ),
                          "바꾸지 못했습니다.",
                        )
                      }
                      className={btn}
                    >
                      <ArrowLeftRight className="size-4" aria-hidden />
                    </button>
                  )}
                </div>
              }
              <div className="mt-2">
                <AssetBlockView block={t.block} onOpen={r.openSource} caption={false} />
              </div>
            </>
          )}
        </div>
      )}
      {templating && t && <TemplateDialog table={t} onClose={() => setTemplating(false)} />}
      {inserting && t && <InsertToReportDialog table={t} onClose={() => setInserting(false)} />}
    </aside>
  );
}
