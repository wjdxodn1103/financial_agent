"use client";

/** 리서치 메모 — 답 그대로(출처 링크를 누르면 원문). 보관·검색용이고 근거 자료가 아니다. */
import ChatMarkdown from "@/components/ChatMarkdown";
import { useMaybeReportActions } from "../../hooks/useReportStudio";
import type { NoteBlock } from "../../types";
import { useCiteComponents } from "../chat/citeLinks";

export function NoteView({ block, onOpen }: { block: NoteBlock; onOpen?: (docId: string, chunk?: string) => void }) {
  const actions = useMaybeReportActions();
  const open = onOpen ?? actions?.openDocument;
  const components = useCiteComponents(open ? (d, c) => open(d, c) : undefined);
  return (
    <div className="rounded-xl bg-neutral-50 px-3.5 py-3">
      <ChatMarkdown content={block.text} className="text-[13px] leading-relaxed text-text-primary" components={components} />
    </div>
  );
}
