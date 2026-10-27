"use client";

/**
 * "자료" 탭 본체 — 올린 자료 / 리포트 목차 / 작성 진행. (OP-FE LibraryPanel 의 폴더 구성에서 분석 원장·메모를 뺐다)
 * 필요한 atom 만 구독한다 — 스트리밍 텍스트 델타로는 다시 그리지 않는다.
 */
import { memo, useState } from "react";
import { useAtomValue } from "jotai";
import { Check, Circle } from "lucide-react";

import { cn } from "@/lib/utils";
import { focusStepAtom, hasDocAtom, modesAtom, reportAtom, sessionAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import { DocumentsFolder } from "./DocumentsFolder";
import { FolderRow } from "./rows";

function GroupLabel({ children }: { children: React.ReactNode }) {
  return <p className="px-2 pt-4 pb-1 text-xs font-semibold tracking-wider text-text-secondary">{children}</p>;
}

function OutlineList() {
  const actions = useReportActions();
  const session = useAtomValue(sessionAtom);
  const focusStep = useAtomValue(focusStepAtom);
  const [open, setOpen] = useState(true);
  const sections = session?.sections ?? [];
  const written = sections.filter((s) => s.status === "written").length;

  return (
    <div>
      <FolderRow open={open} label="리포트 목차" count={sections.length} extra={sections.length ? `${written}개 작성` : undefined} onClick={() => setOpen((v) => !v)} />
      {open && (
        <div className="ml-4 flex flex-col">
          {sections.map((s, i) => (
            <button
              key={s.step}
              type="button"
              title={s.status === "written" ? undefined : "작성 요청"}
              onClick={() => (s.status === "written" ? actions.openSection(s.step) : actions.draft(`${s.title} 써줘`))}
              className={cn("flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-neutral-100", focusStep === s.step && "bg-primary-soft")}
            >
              <span className="w-5 shrink-0 text-center font-mono text-xs text-text-secondary">{i + 1}</span>
              <span className={cn("min-w-0 flex-1 truncate text-sm", s.status === "written" ? "text-text-primary" : "text-text-secondary")}>{s.title}</span>
              {s.status === "written" && <span className="shrink-0 text-xs text-text-secondary tabular-nums">{(s.content ?? "").replace(/\[@[^\]]+\]/g, "").length.toLocaleString()}자</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ProgressMap() {
  const actions = useReportActions();
  const report = useAtomValue(reportAtom);
  const [open, setOpen] = useState(false);
  const entries = report?.progress ?? [];
  return (
    <div>
      <FolderRow open={open} label="작성 진행" count={entries.length} extra={report ? `필수 ${report.stats.requiredCovered}/${report.stats.required}` : undefined} onClick={() => setOpen((v) => !v)} />
      {open && (
        <div className="ml-3 flex flex-col gap-0.5 pt-1">
          {entries.map((e) => (
            <button
              key={e.item.id}
              type="button"
              title={e.item.desc}
              onClick={() => actions.draft(e.covered ? `${e.by[0]?.title ?? e.item.title} 보강해줘` : `${e.item.title} 써줘`)}
              className="flex w-full cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-neutral-100"
            >
              {e.covered ? <Check className="size-3.5 shrink-0 text-primary" aria-hidden /> : <Circle className="size-3 shrink-0 text-neutral-400" aria-hidden />}
              <span className={cn("min-w-0 flex-1 truncate text-xs", e.covered ? "text-text-primary" : "text-text-secondary")}>{e.item.title}</span>
              {e.item.level !== "required" && <span className="shrink-0 text-xs text-text-secondary">권장</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export const LibraryPanel = memo(function LibraryPanel() {
  // 리포트 목차·작성 진행은 문서가 붙어 있거나 문서 작성을 켰을 때만
  const hasDoc = useAtomValue(hasDocAtom);
  const modes = useAtomValue(modesAtom);
  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-2 pb-6">
      <GroupLabel>데이터</GroupLabel>
      <DocumentsFolder />
      {(hasDoc || modes.writing) && (
        <>
          <GroupLabel>리포트</GroupLabel>
          <OutlineList />
          <ProgressMap />
        </>
      )}
    </div>
  );
});
