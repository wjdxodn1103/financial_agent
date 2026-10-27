"use client";

/**
 * 대화 스레드 — 사용자 말풍선과 AI 블록(도구 실행 줄, 섹션 카드, 계획 카드, 본문, 확인 카드). OP-FE PaperThread 이식.
 * 서버가 만든 문자열(질문·섹션 제목·요약)은 그대로 보인다 — 화면에서 다시 해석하지 않는다.
 * 스크롤: 턴이 시작되면 바닥에 붙어 따라가고, 그 턴에 사용자가 스크롤로 개입하면 놓는다. 카드가 새로 생기면 한 번 바닥으로.
 */
import { useEffect, useRef, useState } from "react";
import { useAtomValue } from "jotai";
import { ChevronRight, CircleAlert, FileText, FolderOpen, Loader2, NotebookPen, RotateCcw, Wrench } from "lucide-react";

import ChatMarkdown from "@/components/ChatMarkdown";
import { cn } from "@/lib/utils";
import { activeTableIdAtom, messagesAtom, panelsAtom, streamingAtom, tablesAtom } from "../../atoms";
import { toolLabel } from "../../constants";
import { errorText, useReportActions } from "../../hooks/useReportStudio";
import type { ChatMessage, ToolRun } from "../../types";
import { useWorkspace } from "../../../workspace/context";
import { FEATURES } from "../../../workspace/features";
import { AssetCard, assetIcon } from "../assets/AssetPanel";
import { ApprovalCard } from "./ApprovalCard";
import { useCiteComponents } from "./citeLinks";
import { ImportCards } from "./ImportCards";
import { PlanCard } from "./PlanCard";
import { SectionCard } from "./SectionCard";

const STICK_THRESHOLD = 48;

export function Thread() {
  const messages = useAtomValue(messagesAtom);
  const wrapRef = useRef<HTMLDivElement>(null);
  const followRef = useRef(true);
  const lastUserIdRef = useRef<string | null>(null);
  const cardCountRef = useRef(0);
  const programmaticRef = useRef(0);

  const scrollToBottom = () => {
    const scroller = wrapRef.current?.parentElement;
    if (!scroller) return;
    const before = scroller.scrollTop;
    scroller.scrollTop = scroller.scrollHeight;
    if (scroller.scrollTop !== before) programmaticRef.current += 1;
  };

  useEffect(() => {
    const scroller = wrapRef.current?.parentElement;
    if (!scroller) return;
    const onScroll = () => {
      if (programmaticRef.current > 0) {
        programmaticRef.current -= 1;
        return;
      }
      if (scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight > STICK_THRESHOLD) followRef.current = false;
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    return () => scroller.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser && lastUser.id !== lastUserIdRef.current) {
      lastUserIdRef.current = lastUser.id;
      followRef.current = true;
    }
    const cards = messages.reduce((n, m) => n + (m.approval ? 1 : 0) + (m.plan ? 1 : 0) + (m.sectionUpdates?.length ?? 0), 0);
    const newCard = cards !== cardCountRef.current;
    cardCountRef.current = cards;
    if (newCard || followRef.current) scrollToBottom();
  }, [messages]);

  return (
    <div ref={wrapRef} className="mx-auto flex w-full max-w-[880px] flex-col gap-7 px-6 py-8">
      {messages.map((m, i) =>
        m.role === "user" ? <UserBubble key={m.id} message={m} /> : <AssistantBlock key={m.id} message={m} previous={messages[i - 1]} isLast={i === messages.length - 1} />,
      )}
    </div>
  );
}

function UserBubble({ message }: { message: ChatMessage }) {
  return (
    <div className="flex justify-end">
      <div className="chat-prose max-w-[78%] rounded-[14px_14px_4px_14px] bg-primary-soft px-4 py-2.5 text-sm leading-relaxed text-text-primary">
        <p className="whitespace-pre-wrap">{message.text}</p>
      </div>
    </div>
  );
}

function AssistantBlock({ message, previous, isLast }: { message: ChatMessage; previous?: ChatMessage; isLast: boolean }) {
  const actions = useReportActions();
  const streaming = useAtomValue(streamingAtom);
  const activeTable = useAtomValue(activeTableIdAtom);
  const panels = useAtomValue(panelsAtom);
  const tables = useAtomValue(tablesAtom);
  const ws = useWorkspace();
  // 답 속 출처 링크 → 문서 보기에 그 문단
  const cite = useCiteComponents(actions.openDocument);
  const retryText = previous?.role === "user" ? previous.text : null;
  const canRetry = isLast && !streaming && Boolean(retryText) && (Boolean(message.error) || Boolean(message.aborted));

  return (
    <div className="group flex flex-col gap-4">
      {(message.tools?.length ?? 0) > 0 && <ToolDisclosure tools={message.tools ?? []} />}
      {message.tables?.map((t) => {
        const on = activeTable === t.id && panels.rightOpen && panels.rightTab === "result";
        const full = tables.find((x) => x.id === t.id);
        // 오른쪽 탭을 끈 동안은 표·차트를 답 아래에 그대로(버튼째)
        if (!FEATURES.panelTabs && full) return <AssetCard key={t.id} t={full} inline />;
        const Icon = full ? assetIcon(full) : assetIcon({ kind: "table", chart: null });
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => actions.setActiveTable(t.id)}
            className={cn("flex w-fit cursor-pointer items-center gap-2.5 rounded-2xl px-4 py-3 text-left transition-colors", on ? "bg-primary-soft ring-2 ring-primary/30" : "bg-neutral-100 hover:bg-neutral-200")}
          >
            <Icon className="size-5 text-primary" aria-hidden />
            <span className="text-[14px] font-semibold text-text-primary">{t.title}</span>
          </button>
        );
      })}
      {message.links?.map((l, i) => {
        const Icon = l.kind === "doc" ? FileText : FolderOpen;
        return (
          <button
            key={`${l.id}${i}`}
            type="button"
            onClick={() => (l.kind === "doc" ? ws.nav.openReport(l.id) : actions.openDocument(l.id))}
            className="flex w-fit cursor-pointer items-center gap-2.5 rounded-2xl bg-neutral-100 px-4 py-3 text-left transition-colors hover:bg-neutral-200"
          >
            <Icon className="size-5 text-primary" aria-hidden />
            <span className="text-[14px] font-semibold text-text-primary">{l.title}</span>
          </button>
        );
      })}
      {message.plan && <PlanCard plan={message.plan} />}
      {message.sectionUpdates?.map((u) => <SectionCard key={u.step} msgId={message.id} update={u} />)}
      {message.text && (
        <div className={cn("chat-prose", message.streaming && !message.approval && "stream-caret")}>
          <ChatMarkdown content={message.text} className="text-sm leading-relaxed text-text-primary" components={cite} />
        </div>
      )}
      {message.imports && <ImportCards msgId={message.id} box={message.imports} />}
      {message.approval && <ApprovalCard message={message} />}
      {message.aborted && <p className="px-1 text-xs text-text-secondary">중단했습니다.</p>}
      {message.error && (
        <div className="rounded-md border border-neutral-200 bg-neutral-50 px-2.5 py-2 text-xs font-medium text-neutral-800">{errorText(message.error)}</div>
      )}
      {!message.streaming && !message.error && !message.imports && message.text.trim().length > 20 && (
        <button
          type="button"
          onClick={() => void actions.saveNote(message.id)}
          title="이 답을 메모로 남기기(출처째)"
          className="inline-flex w-fit cursor-pointer items-center gap-1 rounded-md px-1 text-[11px] text-text-secondary opacity-0 transition-opacity group-hover:opacity-100 hover:text-primary"
        >
          <NotebookPen className="size-3" aria-hidden />
          메모로 저장
        </button>
      )}
      {canRetry && retryText && (
        <button
          type="button"
          onClick={() => void actions.send(retryText)}
          className="inline-flex w-fit cursor-pointer items-center gap-1 rounded-md border border-neutral-200 bg-white px-2 py-1 text-xs text-text-secondary hover:border-primary hover:text-primary"
        >
          <RotateCcw className="size-3" aria-hidden />
          다시 시도
        </button>
      )}
    </div>
  );
}

/** 도구 실행 줄 — 기본 접힘(모델 추론 텍스트는 내지 않는다, OP 사용자 결정) */
export function ToolDisclosure({ tools }: { tools: ToolRun[] }) {
  const [open, setOpen] = useState(false);
  const running = tools.filter((x) => x.status === "running").length;
  return (
    <div className="pl-0.5">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="relative flex cursor-pointer items-center gap-2 text-xs text-text-secondary transition-colors hover:text-text-primary">
        <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} aria-hidden />
        <span className="chat-prose">작업 과정</span>
        {running > 0 && <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />}
        <span className="font-mono text-xs">
          {tools.length - running}/{tools.length}
        </span>
      </button>
      {open && (
        <div className="mt-3 flex flex-col gap-2.5">
          {tools.map((x) => (
            <div key={x.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-neutral-200 bg-background-gray px-3 py-1 text-text-secondary">
                {x.status === "running" ? (
                  <Loader2 className="size-3 animate-spin text-primary" aria-hidden />
                ) : x.status === "error" ? (
                  <CircleAlert className="size-3 text-destructive" aria-hidden />
                ) : (
                  <Wrench className="size-3" aria-hidden />
                )}
                <span className="text-text-primary">{toolLabel(x.name)}</span>
              </span>
              {x.args?.query && <span className="text-text-secondary">“{x.args.query}”</span>}
              {x.summary && <span className="text-text-secondary">{x.summary}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
