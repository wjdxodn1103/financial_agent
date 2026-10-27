"use client";

/**
 * 오른쪽 '데이터' — 평소엔 데이터 설정(켠 묶음·추가한 데이터·AI 가 쓰는 데이터 수), AI 가 답·문서에 쓴 근거가 생기면 그 목록.
 * 근거 = 채팅 답의 출처 링크(#cite=문서~문단) + 문서 본문 인용([@문서#문단]). 누르면 원문 확인 창. 본문의 [n]·카드의 '근거'는 그 문장·섹션의 출처를 위에 띄운다.
 */
import { memo, useEffect, useMemo, useState } from "react";
import { useAtom, useAtomValue, useSetAtom } from "jotai";
import { ChevronDown, ChevronRight, FileText, SlidersHorizontal, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useWorkspaceId } from "../../../workspace/context";
import { getChunk } from "../../api";
import { dataScopeAtom, dataSettingsOpenAtom, documentsAtom, evidenceFocusAtom, messagesAtom, reportAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import type { ChunkContext, CiteAnchor, ReportBlock, ReportView } from "../../types";
import { DEFAULT_GROUPS, GROUP_LABEL, GROUPS } from "./DataSettingsDialog";

const CITE = /\(#cite=([^~)\s]+)~([^)\s]+)\)/g;
const MAX_ROWS = 40;

interface Used {
  docId: string;
  chunks: { chunk: string; chat: number; doc: number }[];
}

function sentenceAnchors(report: ReportView | null): { step: string; sentence: string; anchors: CiteAnchor[] }[] {
  const out: { step: string; sentence: string; anchors: CiteAnchor[] }[] = [];
  for (const b of (report?.blocks ?? []) as ReportBlock[]) {
    if (b.kind === "para") b.cites.forEach((c) => out.push({ step: b.step, sentence: c.sentence, anchors: c.anchors }));
    if (b.kind === "list") b.items.forEach((it) => it.cites.forEach((c) => out.push({ step: b.step, sentence: c.sentence, anchors: c.anchors })));
  }
  return out;
}

/** AI 가 쓴 근거 — 문서마다 문단(답에서 몇 번·문서에서 몇 번) */
function useUsed(): Used[] {
  const messages = useAtomValue(messagesAtom);
  const report = useAtomValue(reportAtom);
  return useMemo(() => {
    const by = new Map<string, Map<string, { chat: number; doc: number }>>();
    const add = (docId: string, chunk: string, from: "chat" | "doc") => {
      const m = by.get(docId) ?? new Map<string, { chat: number; doc: number }>();
      const c = m.get(chunk) ?? { chat: 0, doc: 0 };
      c[from] += 1;
      m.set(chunk, c);
      by.set(docId, m);
    };
    for (const msg of messages) if (msg.role === "assistant") for (const x of msg.text.matchAll(CITE)) add(x[1], x[2], "chat");
    for (const s of sentenceAnchors(report)) for (const a of s.anchors) add(a.docId, a.chunk, "doc");
    return [...by.entries()].map(([docId, m]) => ({ docId, chunks: [...m.entries()].map(([chunk, n]) => ({ chunk, ...n })) }));
  }, [messages, report]);
}

function SourceRow({ docId, chunk, note }: { docId: string; chunk: string; note?: string }) {
  const workspaceId = useWorkspaceId();
  const actions = useReportActions();
  const [d, setD] = useState<ChunkContext | null>(null);
  useEffect(() => {
    let cancelled = false;
    getChunk(workspaceId, docId, chunk)
      .then((x) => !cancelled && setD(x))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [workspaceId, docId, chunk]);
  const where = d ? (d.chunk.sheet ? `시트 ${d.chunk.sheet}` : d.chunk.page != null ? `p.${d.chunk.page}` : d.chunk.heading ? `§ ${d.chunk.heading}` : "") : "";
  return (
    <button type="button" onClick={() => actions.openDocument(docId, chunk)} className="flex w-full cursor-pointer flex-col gap-0.5 rounded-lg px-2.5 py-2 text-left hover:bg-neutral-50">
      <span className="flex items-center gap-1.5 text-[11px] text-text-secondary">
        {where && <span className="font-medium text-neutral-600">{where}</span>}
        {d?.chunk.kind === "table" && <span className="rounded bg-neutral-100 px-1">표</span>}
        {note && <span className="ml-auto">{note}</span>}
      </span>
      <span className="line-clamp-2 text-[12px] leading-5 text-text-primary">{d ? d.chunk.text.replace(/\s+/g, " ") : "…"}</span>
    </button>
  );
}

function DocGroup({ used, label, defaultOpen }: { used: Used; label: string; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const chat = used.chunks.reduce((n, c) => n + (c.chat ? 1 : 0), 0);
  const doc = used.chunks.reduce((n, c) => n + (c.doc ? 1 : 0), 0);
  return (
    <div className="rounded-xl bg-white ring-1 ring-neutral-200">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full cursor-pointer items-center gap-2 px-3 py-2.5 text-left">
        {open ? <ChevronDown className="size-3.5 shrink-0 text-text-secondary" aria-hidden /> : <ChevronRight className="size-3.5 shrink-0 text-text-secondary" aria-hidden />}
        <FileText className="size-4 shrink-0 text-neutral-500" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-text-primary">{label}</span>
        <span className="shrink-0 text-[11px] text-text-secondary">{[chat && `답변 ${chat}`, doc && `문서 ${doc}`].filter(Boolean).join(" · ")}</span>
      </button>
      {open && (
        <div className="border-t border-neutral-100 px-1 py-1">
          {used.chunks.slice(0, MAX_ROWS).map((c) => (
            <SourceRow key={c.chunk} docId={used.docId} chunk={c.chunk} />
          ))}
        </div>
      )}
    </div>
  );
}

/** 본문의 [n]·카드 '근거'로 고른 문장(또는 섹션)의 출처 */
function FocusSources() {
  const [focus, setFocus] = useAtom(evidenceFocusAtom);
  const report = useAtomValue(reportAtom);
  const documents = useAtomValue(documentsAtom);
  if (!focus) return null;
  const hits = sentenceAnchors(report).filter((s) => s.step === focus.step && (!focus.sentence || s.sentence === focus.sentence));
  const anchors = hits.flatMap((s) => s.anchors).filter((a, i, xs) => xs.findIndex((x) => x.docId === a.docId && x.chunk === a.chunk) === i);
  const title = report?.blocks.find((b) => b.kind === "heading" && b.step === focus.step) as { text?: string } | undefined;
  return (
    <section className="rounded-xl bg-primary-soft/50 p-2 ring-1 ring-primary-soft-border">
      <div className="flex items-start gap-2 px-1.5 pt-1">
        <p className="min-w-0 flex-1 text-[12px] leading-5 text-text-primary">{focus.sentence ? `“${focus.sentence}”` : `${title?.text ?? "이 섹션"}의 출처`}</p>
        <button type="button" aria-label="닫기" onClick={() => setFocus(null)} className="cursor-pointer rounded p-0.5 text-text-secondary hover:bg-white">
          <X className="size-3.5" aria-hidden />
        </button>
      </div>
      <div className="mt-1">
        {anchors.length === 0 && <p className="px-2.5 py-2 text-[12px] text-text-secondary">출처가 없습니다.</p>}
        {anchors.slice(0, MAX_ROWS).map((a) => (
          <SourceRow key={`${a.docId}#${a.chunk}`} docId={a.docId} chunk={a.chunk} note={`[${a.n}] ${documents.find((d) => d.id === a.docId)?.label ?? ""}`} />
        ))}
      </div>
    </section>
  );
}

export const DataPanel = memo(function DataPanel() {
  const actions = useReportActions();
  const scope = useAtomValue(dataScopeAtom);
  const documents = useAtomValue(documentsAtom);
  const openSettings = useSetAtom(dataSettingsOpenAtom);
  const used = useUsed();
  const [listOpen, setListOpen] = useState(false);
  const groups = scope?.groups ?? DEFAULT_GROUPS;
  const inUse = documents.filter((d) => !d.off);
  const labelOf = (id: string) => documents.find((d) => d.id === id)?.label ?? scope?.docs.find((d) => d.id === id)?.label ?? id.slice(0, 8);

  return (
    <div className="thin-scrollbar flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto bg-neutral-50/60 px-3 pt-3 pb-8">
      <FocusSources />

      <section className="rounded-xl bg-white p-3 ring-1 ring-neutral-200">
        <div className="flex items-center gap-2">
          <p className="min-w-0 flex-1 text-[13px] font-semibold text-text-primary">데이터 설정</p>
          <button type="button" onClick={() => openSettings(true)} className="flex h-7 cursor-pointer items-center gap-1 rounded-md px-2 text-[12px] font-medium text-primary hover:bg-primary-soft">
            <SlidersHorizontal className="size-3.5" aria-hidden />
            바꾸기
          </button>
        </div>
        <div className="mt-2 flex flex-col gap-1">
          {GROUPS.map((g) => (
            <p key={g} className={cn("flex items-center gap-2 text-[13px]", groups[g] ? "text-text-primary" : "text-neutral-400")}>
              <span className={cn("size-2 shrink-0 rounded-full", groups[g] ? "bg-primary" : "bg-neutral-300")} />
              <span className="flex-1">{GROUP_LABEL[g]}</span>
              <span className="text-[12px] tabular-nums">{groups[g] ? "켬" : "끔"}</span>
            </p>
          ))}
        </div>
        {(scope?.docs.length ?? 0) > 0 && (
          <div className="mt-2.5 flex flex-wrap gap-1">
            {scope!.docs.map((d) => (
              <span key={d.id} className="max-w-full truncate rounded-md bg-primary-soft px-2 py-0.5 text-[12px] text-primary-soft-foreground">
                {d.label}
              </span>
            ))}
          </div>
        )}
        <button type="button" onClick={() => setListOpen((v) => !v)} className="mt-3 flex w-full cursor-pointer items-center gap-1 text-[12px] text-text-secondary hover:text-text-primary">
          {listOpen ? <ChevronDown className="size-3.5" aria-hidden /> : <ChevronRight className="size-3.5" aria-hidden />}
          AI가 쓰는 데이터 {inUse.length}개
        </button>
        {listOpen && (
          <div className="mt-1 flex flex-col">
            {inUse.map((d) => (
              <button key={d.id} type="button" onClick={() => actions.openDocument(d.id)} className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-left text-[12px] text-text-primary hover:bg-neutral-50">
                <FileText className="size-3.5 shrink-0 text-neutral-400" aria-hidden />
                <span className="truncate">{d.label}</span>
              </button>
            ))}
            {inUse.length === 0 && <p className="px-1.5 py-1 text-[12px] text-text-secondary">고른 데이터가 없습니다.</p>}
          </div>
        )}
      </section>

      {used.length > 0 && (
        <section>
          <p className="px-1 pb-2 text-[13px] font-semibold text-text-primary">AI가 쓴 근거</p>
          <div className="flex flex-col gap-2">
            {used.map((u, i) => (
              <DocGroup key={u.docId} used={u} label={labelOf(u.docId)} defaultOpen={i < 2} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
});
