"use client";

/**
 * 첫 메시지를 보내기 전 시작 화면(제미나이식) — 가운데 인사 + 입력창 + 추천 카드 4개.
 * 카드는 BE app/start_cards.py 가 내 기록(할 일·검토 요청·쓰다 만 문서·되풀이한 질문·새 자료·자주 쓴 양식)으로 고른다.
 * 카드를 누르면: 질문 보내기(필요한 모드를 켜고) · 문서 열기 · 자료 속 표 창 · 할 일 화면.
 */
import { useEffect, useState } from "react";
import { useAtomValue, useSetAtom } from "jotai";
import { CalendarClock, ClipboardCheck, Copy, FilePlus2, FileText, NotebookPen, Repeat, Search, Sparkles, Table2, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import { useWorkspace } from "../../../workspace/context";
import { FEATURES } from "../../../workspace/features";
import { DocTablesDialog } from "../../../workspace/components/DocTablesDialog";
import { getStartCards, type StartCard } from "../../api";
import { formatPickAtom, modesAtom, sessionAtom, streamingAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import type { DocumentCard } from "../../types";
import { Composer } from "../chat/Composer";

const ICON: Record<string, LucideIcon> = {
  due: CalendarClock,
  review: ClipboardCheck,
  continue: FileText,
  routine: Repeat,
  same: Copy,
  template: Table2,
  format: FilePlus2,
  new: Sparkles,
  d_research: Search,
  d_peer: Table2,
  d_writing: FilePlus2,
  d_assets: NotebookPen,
  d_numbers: Table2,
};

export function StartScreen({ composer = true }: { composer?: boolean }) {
  const actions = useReportActions();
  const ws = useWorkspace();
  const session = useAtomValue(sessionAtom);
  const modes = useAtomValue(modesAtom);
  const streaming = useAtomValue(streamingAtom);
  const setPicking = useSetAtom(formatPickAtom);
  const [cards, setCards] = useState<StartCard[] | null>(null);
  const [tablesOf, setTablesOf] = useState<Pick<DocumentCard, "id" | "label"> | null>(null);

  useEffect(() => {
    if (!session?.id || !FEATURES.startCards) return;
    let cancelled = false;
    getStartCards(session.id)
      .then((r) => !cancelled && setCards(r.cards))
      .catch(() => !cancelled && setCards([]));
    return () => {
      cancelled = true;
    };
  }, [session?.id]);

  const run = (c: StartCard) => {
    const a = c.action;
    if (a.type === "send") {
      // 모드는 하나씩 — 카드가 켜는 모드만
      if (a.modes && (a.modes.research || a.modes.writing)) actions.setModes({ research: !!a.modes.research && !a.modes.writing, writing: !!a.modes.writing });
      void actions.send(a.text);
    } else if (a.type === "format") {
      void actions.setReportType(a.reportType).then((ok) => ok && actions.setModes({ research: false, writing: true }));
    } else if (a.type === "pick") setPicking(true);
    else if (a.type === "open") ws.nav.openReport(a.reportId);
    else if (a.type === "tables") setTablesOf({ id: a.docId, label: a.label });
    else ws.nav.view(a.view);
  };

  return (
    <div className="flex h-full flex-col items-center justify-center px-6 pb-10">
      <div className="w-full max-w-[760px]">
        <h1 className="text-[32px] leading-tight font-semibold tracking-tight">
          <span className="bg-gradient-to-r from-[#3182F6] via-[#7C5CF5] to-[#E0559B] bg-clip-text text-transparent">안녕하세요,</span>
        </h1>
        <p className="mt-0.5 text-[32px] leading-tight font-semibold tracking-tight text-neutral-400">무엇을 도와드릴까요?</p>

        {composer && (
          <div className="mt-7">
            <Composer centered />
          </div>
        )}

        <div className={cn("mt-3 grid grid-cols-2 gap-2.5 lg:grid-cols-4", !FEATURES.startCards && "hidden")}>
          {(cards ?? []).map((c) => {
            const Icon = ICON[c.kind] ?? Sparkles;
            return (
              <button
                key={c.id}
                type="button"
                disabled={streaming}
                onClick={() => run(c)}
                className="group flex h-[118px] cursor-pointer flex-col justify-between rounded-2xl bg-neutral-100/80 p-3.5 text-left transition-colors hover:bg-neutral-200/70 disabled:cursor-default disabled:opacity-60"
              >
                <span className="line-clamp-3 text-[14px] leading-snug font-medium text-text-primary">{c.title}</span>
                <span className="flex items-end justify-between gap-2">
                  <span className="truncate text-[12px] text-text-secondary">{c.sub}</span>
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-white text-neutral-600 group-hover:text-primary">
                    <Icon className="size-4" aria-hidden />
                  </span>
                </span>
              </button>
            );
          })}
          {cards === null && [0, 1, 2, 3].map((i) => <span key={i} className="h-[118px] animate-pulse rounded-2xl bg-neutral-100/80" />)}
        </div>
      </div>
      {tablesOf && <DocTablesDialog doc={tablesOf as DocumentCard} onClose={() => setTablesOf(null)} />}
    </div>
  );
}
