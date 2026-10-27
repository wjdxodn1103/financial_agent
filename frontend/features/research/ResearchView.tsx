"use client";

/**
 * AI 채팅 — 가운데 대화, 오른쪽 결과 패널(표 · 문서 보기). 대화는 내 것만 보이고, 표는 드라이브에 저장하면 멤버가 본다.
 * 답 속 출처 링크(#cite=문서~문단)와 표 칸을 누르면 오른쪽 '문서 보기'에 원문이 강조되어 열린다.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { Components } from "react-markdown";
import { CircleAlert, RotateCcw, SendHorizontal, Square, Table2 } from "lucide-react";

import ChatMarkdown from "@/components/ChatMarkdown";
import { cn } from "@/lib/utils";
import { ToolDisclosure } from "../report/components/chat/Thread";
import { statusLabel } from "../report/constants";
import { errorText } from "../report/hooks/useReportStudio";
import { useWorkspace } from "../workspace/context";
import { listTemplates } from "./api";
import { ResultPanel } from "./ResultPanel";
import type { ResearchMessage, ResearchTemplate } from "./types";
import { useResearch } from "./useResearch";

export function ResearchView({ chatId, tableId }: { chatId: string | null; tableId: string | null }) {
  const ws = useWorkspace();
  const r = useResearch(ws.workspaceId, chatId, tableId, (id) => ws.nav.openResearch(id, null, true));
  const [templates, setTemplates] = useState<ResearchTemplate[]>([]);
  const [draft, setDraft] = useState({ text: "", tick: 0 });
  const scrollRef = useRef<HTMLDivElement>(null);
  const empty = r.messages.length === 0 && !r.loading;
  const panel = r.tables.length > 0 || r.viewing !== null;

  useEffect(() => {
    void listTemplates(ws.workspaceId)
      .then(setTemplates)
      .catch(() => undefined);
  }, [ws.workspaceId, r.tables.length]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [r.messages]);

  const components = useMemo<Partial<Components>>(
    () => ({
      a: ({ href, children }) => {
        const m = /^#cite=([^~]+)~(.+)$/.exec(href ?? "");
        if (m) {
          return (
            <button type="button" onClick={() => r.openSource(m[1], m[2])} className="cursor-pointer text-primary underline-offset-2 hover:underline">
              {children}
            </button>
          );
        }
        return (
          <a href={href} target="_blank" rel="noreferrer noopener" className="text-primary underline underline-offset-2">
            {children}
          </a>
        );
      },
    }),
    [r.openSource],
  );

  const composer = (
    <Composer
      streaming={r.streaming}
      onSend={(t) => (setDraft({ text: "", tick: 0 }), void r.send(t))}
      onStop={r.stop}
      draft={draft}
      placeholder={r.active ? "이 표에 대해 묻거나 고칠 점을 말해 주세요" : "찾을 내용이나 만들 표를 말해 주세요"}
    />
  );

  return (
    <div className="flex min-h-0 flex-1">
      <section className="flex min-w-[420px] flex-1 flex-col bg-white">
        {empty ? (
          <div className="flex flex-1 flex-col items-center justify-center px-6 pb-16">
            <h1 className="text-[26px] font-bold tracking-tight text-text-primary">무엇을 찾아볼까요?</h1>
            <div className="mt-6 w-full max-w-[720px]">{composer}</div>
            {templates.length > 0 && (
              <div className="mt-4 flex max-w-[720px] flex-wrap justify-center gap-2">
                {templates.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() =>
                      setDraft({
                        text: `'${t.name}' 양식으로 `,
                        tick: Date.now(),
                      })
                    }
                    className="flex cursor-pointer items-center gap-1.5 rounded-full bg-neutral-100 px-3.5 py-1.5 text-[13px] font-medium text-neutral-700 transition-colors hover:bg-primary-soft hover:text-primary"
                  >
                    <Table2 className="size-3.5" aria-hidden />
                    {t.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <>
            <div ref={scrollRef} className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto flex w-full max-w-[760px] flex-col gap-7 px-6 py-8">
                {r.messages.map((m, i) =>
                  m.role === "user" ? (
                    <div key={m.id} className="flex justify-end">
                      <div className="chat-prose max-w-[78%] rounded-[14px_14px_4px_14px] bg-primary-soft px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap text-text-primary">{m.text}</div>
                    </div>
                  ) : (
                    <Assistant
                      key={m.id}
                      m={m}
                      components={components}
                      activeId={r.active?.id ?? null}
                      onTable={(id) => (r.setActiveId(id), r.setTab("result"))}
                      retry={i === r.messages.length - 1 && !r.streaming && (m.error || m.aborted) && r.messages[i - 1]?.role === "user" ? () => void r.send(r.messages[i - 1].text) : undefined}
                    />
                  ),
                )}
              </div>
            </div>
            {r.streaming && (
              <div className="mx-auto flex w-full max-w-[760px] items-center gap-2 px-7 py-1 text-sm text-text-secondary">
                <span className="dot-bounce flex items-center gap-1" aria-hidden>
                  <span />
                  <span />
                  <span />
                </span>
                {statusLabel(r.stage) && <span>{statusLabel(r.stage)}…</span>}
              </div>
            )}
            <div className="shrink-0 px-4 pt-2 pb-4">
              <div className="mx-auto w-full max-w-[760px]">{composer}</div>
            </div>
          </>
        )}
      </section>
      {panel && <ResultPanel r={r} />}
    </div>
  );
}

function Assistant({ m, components, activeId, onTable, retry }: { m: ResearchMessage; components: Partial<Components>; activeId: string | null; onTable: (id: string) => void; retry?: () => void }) {
  return (
    <div className="flex flex-col gap-3.5">
      {(m.tools?.length ?? 0) > 0 && <ToolDisclosure tools={m.tools ?? []} />}
      {m.tables?.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => onTable(t.id)}
          className={cn(
            "flex w-fit cursor-pointer items-center gap-2.5 rounded-2xl px-4 py-3 text-left transition-colors",
            activeId === t.id ? "bg-primary-soft ring-2 ring-primary/30" : "bg-neutral-100 hover:bg-neutral-200",
          )}
        >
          <Table2 className="size-5 text-primary" aria-hidden />
          <span className="text-[14px] font-semibold text-text-primary">{t.title}</span>
        </button>
      ))}
      {m.text && (
        <div className={cn("chat-prose", m.streaming && "stream-caret")}>
          <ChatMarkdown content={m.text} className="text-sm leading-relaxed text-text-primary" components={components} />
        </div>
      )}
      {m.aborted && <p className="px-1 text-xs text-text-secondary">중단했습니다.</p>}
      {m.error && (
        <div className="flex items-center gap-1.5 rounded-md bg-neutral-50 px-2.5 py-2 text-xs font-medium text-neutral-800">
          <CircleAlert className="size-3.5 text-neutral-500" aria-hidden />
          {errorText(m.error)}
        </div>
      )}
      {retry && (
        <button
          type="button"
          onClick={retry}
          className="inline-flex w-fit cursor-pointer items-center gap-1 rounded-md border border-neutral-200 bg-white px-2 py-1 text-xs text-text-secondary hover:border-primary hover:text-primary"
        >
          <RotateCcw className="size-3" aria-hidden />
          다시 시도
        </button>
      )}
    </div>
  );
}

function Composer({ streaming, onSend, onStop, draft, placeholder }: { streaming: boolean; onSend: (t: string) => void; onStop: () => void; draft: { text: string; tick: number }; placeholder: string }) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  useEffect(() => {
    if (!draft.tick) return;
    setText(draft.text);
    ref.current?.focus();
  }, [draft]);

  const submit = () => {
    const v = text.trim();
    if (!v || streaming) return;
    setText("");
    onSend(v);
  };

  return (
    <div className="rounded-2xl border border-neutral-200 bg-white shadow-[0_2px_8px_rgba(0,27,55,0.04)] transition-colors focus-within:border-neutral-400">
      <textarea
        ref={ref}
        rows={1}
        value={text}
        placeholder={streaming ? "응답을 기다리는 중…" : placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        className="chat-prose block max-h-40 w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[15px] leading-6 text-text-primary outline-none placeholder:text-text-secondary"
      />
      <div className="flex justify-end px-2.5 pb-2.5">
        {streaming ? (
          <button type="button" aria-label="중단" title="중단" onClick={onStop} className="flex size-8 cursor-pointer items-center justify-center rounded-lg bg-neutral-900 text-white hover:bg-neutral-700">
            <Square className="size-3 fill-current" />
          </button>
        ) : (
          <button
            type="button"
            aria-label="보내기"
            title="보내기"
            onClick={submit}
            disabled={!text.trim()}
            className="flex size-8 cursor-pointer items-center justify-center rounded-lg bg-primary text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-neutral-400"
          >
            <SendHorizontal className="size-4" />
          </button>
        )}
      </div>
    </div>
  );
}
