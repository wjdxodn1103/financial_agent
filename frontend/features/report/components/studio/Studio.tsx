"use client";

/**
 * AI 작업 — 한 화면 3열(OP-FE PaperStudio 의 배치 그대로).
 *   가운데: 대화(스레드 또는 시작 화면) + 상태 줄 + 입력창(리서치·문서 작성 모드)
 *   오른쪽 1: 문서(원고) — 위쪽 '문서' 토글로 열고 닫는다. 작업 중인 문서가 없으면 안내 한 줄
 *   오른쪽 2: 에셋(표·차트·메모) / 자료 / 보기(문서 뷰어) / 근거 탭 패널 — 폭 조절
 * 셸은 배치에 필요한 atom 만 구독한다(스트리밍 델타로 리포트·자료까지 다시 그려지지 않게).
 */
import { useCallback, useState } from "react";
import { useAtomValue } from "jotai";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { canChatAtom, hasDocAtom, hasUserMessageAtom, loadErrorAtom, loadingAtom, modesAtom, panelsAtom, providerAtom, tablesAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import { AssetPanel } from "../assets/AssetPanel";
import { Composer } from "../chat/Composer";
import { StatusLine } from "../chat/StatusLine";
import { Thread } from "../chat/Thread";
import { LibraryPanel } from "../library/LibraryPanel";
import { NumberPanel } from "../numbers/NumberPanel";
import { ReportView } from "../report/ReportView";
import { ReviewPanel } from "../review/ReviewPanel";
import { CitationEvidence } from "../viewer/CitationEvidence";
import { DocumentViewer } from "../viewer/DocumentViewer";
import { FEATURES } from "../../../workspace/features";
import { FormatPickDialog } from "../chat/FormatPickDialog";
import { DataPanel } from "../data/DataPanel";
import { DataSettingsDialog } from "../data/DataSettingsDialog";
import { SourceModal } from "../viewer/SourceModal";
import { StartScreen } from "./StartScreen";
import { RIGHT_TABS } from "./tabs";
import { TopBar } from "./TopBar";

function RightPanel({ showDoc }: { showDoc: boolean }) {
  const actions = useReportActions();
  const panels = useAtomValue(panelsAtom);
  const modes = useAtomValue(modesAtom);
  const tables = useAtomValue(tablesAtom);
  const [dragging, setDragging] = useState(false);
  // 근거·숫자 출처 = 문서 본문이 있을 때(에셋은 모드와 상관없이 늘)
  const tabs = RIGHT_TABS.filter((t) => (t.id === "evidence" || t.id === "numbers" ? showDoc : true));
  // 저장해 둔 탭이 지금 숨은 탭이면(다른 작업에서 연 결과 탭 등) 데이터 탭으로
  const tab = tabs.some((t) => t.id === panels.rightTab) ? panels.rightTab : "library";

  // 왼쪽 가장자리 드래그로 폭 조절(포인터 캡처 — 패널 밖으로 나가도 따라온다)
  const onResizeStart = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = panels.rightWidth;
      const target = e.currentTarget;
      target.setPointerCapture(e.pointerId);
      setDragging(true);
      const onMove = (ev: PointerEvent) => actions.setRightWidth(startWidth + (startX - ev.clientX));
      const onUp = () => {
        target.removeEventListener("pointermove", onMove);
        target.removeEventListener("pointerup", onUp);
        target.removeEventListener("pointercancel", onUp);
        setDragging(false);
      };
      target.addEventListener("pointermove", onMove);
      target.addEventListener("pointerup", onUp);
      target.addEventListener("pointercancel", onUp);
    },
    [actions, panels.rightWidth],
  );

  return (
    <aside style={{ width: panels.rightWidth }} className="relative flex h-full shrink-0 flex-col overflow-hidden border-l border-neutral-200 bg-white">
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="패널 폭 조절"
        title="패널 폭 조절"
        onPointerDown={onResizeStart}
        className={cn("absolute inset-y-0 left-0 z-10 w-1.5 cursor-col-resize touch-none transition-colors", dragging ? "bg-neutral-400" : "hover:bg-neutral-300")}
      />
      {!FEATURES.panelTabs ? (
        <>
          <div className="flex h-10 shrink-0 items-center border-b border-neutral-200 px-4">
            <p className="text-[13px] font-semibold text-text-primary">데이터</p>
          </div>
          <DataPanel />
        </>
      ) : (
        <>
          <div className="flex h-10 shrink-0 items-center gap-1 border-b border-neutral-200 pr-2 pl-3">
            {tabs.map((t) => {
              const Icon = t.icon;
              const on = tab === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  aria-pressed={on}
                  title={t.label}
                  aria-label={t.label}
                  onClick={() => actions.setRightTab(t.id)}
                  className={cn(
                    "flex h-7 shrink-0 cursor-pointer items-center gap-1.5 rounded-md px-2.5 text-xs font-medium whitespace-nowrap transition-colors",
                    on ? "bg-primary-soft text-primary-soft-foreground" : "text-text-secondary hover:bg-neutral-100 hover:text-text-primary",
                  )}
                >
                  <Icon className="size-3.5" aria-hidden />
                  {/* 탭이 다섯이라 좁은 패널에서는 지금 탭만 이름을 보인다 */}
                  {(on || panels.rightWidth >= 480) && t.label}
                </button>
              );
            })}
          </div>
          <div className="flex min-h-0 flex-1 flex-col">
            {tab === "result" ? (
              <AssetPanel />
            ) : tab === "library" ? (
              <LibraryPanel />
            ) : tab === "evidence" ? (
              <CitationEvidence />
            ) : tab === "numbers" ? (
              <NumberPanel />
            ) : (
              <DocumentViewer />
            )}
          </div>
        </>
      )}
    </aside>
  );
}

function NoProviderCard() {
  return (
    <div className="shrink-0 border-t border-neutral-200 bg-white px-4 py-4">
      <div className="mx-auto max-w-[880px] rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        NVIDIA API 키가 설정되지 않았습니다. <code className="rounded bg-white px-1">backend/.env</code> 에 <code className="rounded bg-white px-1">NVIDIA_API_KEY</code> 를 넣고 백엔드를 다시 실행해 주세요.
      </div>
    </div>
  );
}

export function Studio() {
  const actions = useReportActions();
  const loading = useAtomValue(loadingAtom);
  const loadError = useAtomValue(loadErrorAtom);
  const provider = useAtomValue(providerAtom);
  const panels = useAtomValue(panelsAtom);
  const hasUserMessage = useAtomValue(hasUserMessageAtom);
  const canChat = useAtomValue(canChatAtom);
  const hasDoc = useAtomValue(hasDocAtom);
  const modes = useAtomValue(modesAtom);
  const showDoc = hasDoc || modes.writing;

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-text-secondary">
        <span className="dot-bounce mr-2 inline-flex items-center gap-1" aria-hidden>
          <span />
          <span />
          <span />
        </span>
        불러오는 중
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <p className="text-sm text-red-600">{loadError}</p>
        <Button variant="outline" onClick={() => void actions.reload()}>
          다시 시도
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-white">
      <TopBar />
      <div className="thin-scrollbar flex min-h-0 flex-1 overflow-x-auto">
        <main className="flex min-w-[380px] flex-1 basis-0 flex-col bg-white">
          {/* 작성자가 아닌 멤버 — 에이전트 대화는 작성자의 것이라 보이지 않고(대화는 개인, 기록은 공유) 그 자리에 검토 목록 */}
          <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">{!canChat ? <ReviewPanel /> : hasUserMessage ? <Thread /> : <StartScreen composer={provider?.kind !== "none"} />}</div>
          {canChat && !hasUserMessage && provider?.kind === "none" && <NoProviderCard />}
          {canChat && hasUserMessage && (
            <>
              <div className="mx-auto w-full max-w-[880px] shrink-0 px-4">
                <StatusLine />
              </div>
              {provider?.kind === "none" ? <NoProviderCard /> : <Composer />}
            </>
          )}
        </main>

        {panels.reportOpen && (
          <section className="flex min-w-[440px] flex-1 shrink-0 basis-0 flex-col border-l border-neutral-200 bg-white">
            {hasDoc ? <ReportView /> : <p className="flex flex-1 items-center justify-center text-[14px] text-text-secondary">작업 중인 문서가 없습니다.</p>}
          </section>
        )}

        {panels.rightOpen && <RightPanel showDoc={showDoc} />}
      </div>
      <SourceModal />
      <FormatPickDialog />
      <DataSettingsDialog />
    </div>
  );
}
