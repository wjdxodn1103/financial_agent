"use client";

/**
 * 입력창 — Enter 전송 / Shift+Enter 줄바꿈 / 한글 조합 중 Enter 무시(IME 가드), 스트리밍 중 중단 버튼, 서버 추천 칩.
 * 진행 맵·빈 섹션 클릭으로 들어온 초안은 composerDraft 의 tick 으로 채운다. (OP-FE PaperComposer 이식)
 * 아래 줄 왼쪽 = (양식 샘플 올리기 — FEATURES.chatSampleImport) · 모드(리서치·문서 작성) 하나씩 — 둘 다 끄면 자료 찾기·문서 쓰기 없는 대화.
 * 문서 작성을 처음 켤 때(양식·섹션 없음) 양식 고르기 창(FormatPickDialog)이 뜬다. 양식은 중간에 바꾸지 않는다.
 */
import { useEffect, useRef, useState } from "react";
import { useAtomValue, useSetAtom } from "jotai";
import { Paperclip, PenLine, SendHorizontal, Square, Table2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { composerDraftAtom, formatPickAtom, hasUserMessageAtom, modesAtom, sessionAtom, streamingAtom, suggestionsAtom } from "../../atoms";
import { FEATURES } from "../../../workspace/features";
import { useReportActions } from "../../hooks/useReportStudio";
import type { Modes } from "../../types";

const PLACEHOLDER: Record<string, string> = {
  none: "무엇이든 물어보세요",
  research: "조사·정리할 것을 말해 주세요 (예: 가온전자·나래바이오 2024 Peer 표)",
  writing: "쓸 섹션이나 고칠 곳을 말해 주세요 (예: 실적 분석 써줘)",
  both: "조사하거나 쓸 것을 말해 주세요",
};

function placeholderOf(m: Modes): string {
  return PLACEHOLDER[m.research && m.writing ? "both" : m.research ? "research" : m.writing ? "writing" : "none"];
}

function ModeToggle({ on, icon: Icon, label, onClick }: { on: boolean; icon: typeof PenLine; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "flex h-7 cursor-pointer items-center gap-1 rounded-full px-2.5 text-xs font-medium transition-colors",
        on ? "bg-primary-soft text-primary" : "text-text-secondary hover:bg-neutral-100 hover:text-text-primary",
      )}
    >
      <Icon className="size-3.5" aria-hidden />
      {label}
    </button>
  );
}

/** centered = 시작 화면 가운데(위 줄·배경 없이, 면책 문구 없이) */
export function Composer({ centered = false }: { centered?: boolean }) {
  const actions = useReportActions();
  const streaming = useAtomValue(streamingAtom);
  const session = useAtomValue(sessionAtom);
  const hasUserMessage = useAtomValue(hasUserMessageAtom);
  const suggestions = useAtomValue(suggestionsAtom);
  const draft = useAtomValue(composerDraftAtom);
  const modes = useAtomValue(modesAtom);
  const setPicking = useSetAtom(formatPickAtom);
  const [text, setText] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);
  const sampleRef = useRef<HTMLInputElement>(null);
  const disabled = streaming || !session;
  const chips = hasUserMessage ? suggestions : [];

  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  useEffect(() => {
    if (!draft.tick) return;
    setText(draft.text);
    taRef.current?.focus();
  }, [draft]);

  const submit = () => {
    const value = text.trim();
    if (!value || disabled) return;
    setText("");
    void actions.send(value);
  };

  return (
    <div className={cn("shrink-0", centered ? "" : "border-t border-neutral-200 bg-white px-4 pt-3 pb-4")}>
      <div className={cn("mx-auto w-full", centered ? "" : "max-w-[880px]")}>
        {chips.length > 0 && !streaming && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {chips.map((chip) => (
              <button
                key={chip}
                type="button"
                disabled={disabled}
                onClick={() => void actions.send(chip)}
                className="cursor-pointer rounded-full border border-neutral-200 bg-neutral-50 px-3 py-1 text-xs text-text-secondary transition-colors hover:border-primary-soft-border hover:bg-primary-soft hover:text-primary-soft-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                {chip}
              </button>
            ))}
          </div>
        )}
        <div
          className={cn(
            "border border-neutral-200 bg-white transition-colors focus-within:border-neutral-400",
            centered ? "rounded-3xl px-1 py-1 shadow-[0_2px_12px_rgba(0,27,55,0.06)]" : "rounded-xl",
            disabled && "opacity-70",
          )}
        >
          <textarea
            ref={taRef}
            rows={1}
            value={text}
            disabled={!session}
            placeholder={streaming ? "응답을 기다리는 중…" : placeholderOf(modes)}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            className="chat-prose block max-h-40 w-full resize-none bg-transparent px-3 pt-3 pb-1 text-sm leading-6 text-text-primary outline-none placeholder:text-text-secondary"
          />
          <div className="flex items-center gap-1 px-2.5 pb-2.5">
            {FEATURES.chatSampleImport && (
              <>
                <button
                  type="button"
                  title="양식 샘플 올리기(Word·PDF) — 표·차트·리포트 양식으로 등록"
                  aria-label="양식 샘플 올리기"
                  disabled={disabled}
                  onClick={() => sampleRef.current?.click()}
                  className="flex size-7 cursor-pointer items-center justify-center rounded-full text-text-secondary hover:bg-neutral-100 hover:text-text-primary disabled:opacity-40"
                >
                  <Paperclip className="size-3.5" aria-hidden />
                </button>
                <input
                  ref={sampleRef}
                  type="file"
                  accept=".docx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (f) void actions.importSample(f);
                  }}
                />
              </>
            )}
            {/* 모드는 하나씩 — 누르면 다른 모드는 꺼진다(둘 다 꺼지면 일반 대화) */}
            <ModeToggle on={modes.research} icon={Table2} label="리서치" onClick={() => actions.setModes({ research: !modes.research, writing: false })} />
            <ModeToggle
              on={modes.writing}
              icon={PenLine}
              label="문서 작성"
              onClick={() =>
                !modes.writing && session?.reportType === "free" && !session.sections.length
                  ? setPicking(true)
                  : actions.setModes({
                      research: false,
                      writing: !modes.writing,
                    })
              }
            />
            <span className="flex-1" />
            {streaming ? (
              <button
                type="button"
                aria-label="중단"
                title="중단"
                onClick={() => actions.stop()}
                className="flex size-8 cursor-pointer items-center justify-center rounded-md bg-neutral-900 text-white hover:bg-neutral-700"
              >
                <Square className="size-3 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                aria-label="보내기"
                title="보내기"
                onClick={submit}
                disabled={disabled || !text.trim()}
                className="flex size-8 cursor-pointer items-center justify-center rounded-md bg-neutral-900 text-white hover:bg-neutral-700 disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-neutral-400"
              >
                <SendHorizontal className="size-4" />
              </button>
            )}
          </div>
        </div>
        {!centered && <p className="mt-2 text-center text-[11px] text-text-secondary">AI 는 실수할 수 있습니다. 투자 판단의 책임은 이용자에게 있습니다.</p>}
      </div>
    </div>
  );
}
