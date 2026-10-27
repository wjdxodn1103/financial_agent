"use client";

/**
 * 근거 탭 — 섹션 하나의 출처 달린 문장을 나열하고, 문장을 펼치면 출처마다 **근거 문단**(앞뒤 문단 토글)을 그때 불러온다.
 * OP-FE CitationEvidence 와 같은 화면이지만 데이터가 더 단순하다: 본문 토큰 `[@문서#문단]` 이 곧 앵커라서
 * 리포트 뷰(BE 조립)의 cites 만으로 목록을 만든다(판정 결과를 따로 저장하지 않는다).
 * evidenceFocusAtom(본문의 [n]·카드의 "근거")이 바뀌면 그 섹션으로 가서 같은 문장을 펼친다.
 */
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useAtomValue } from "jotai";
import { ChevronDown, ChevronRight, FileText, ScrollText } from "lucide-react";

import { cn } from "@/lib/utils";
import { getChunk } from "../../api";
import { documentsAtom, evidenceFocusAtom, reportAtom, sessionAtom } from "../../atoms";
import { useWorkspaceId } from "../../../workspace/context";
import { useReportActions } from "../../hooks/useReportStudio";
import { ChunkBody } from "./ChunkBody";
import type { ChunkContext, CiteAnchor, ReportBlock, ReportView } from "../../types";

interface SentenceEntry {
  sentence: string;
  anchors: CiteAnchor[];
}

function entriesBySection(report: ReportView | null): Map<string, SentenceEntry[]> {
  const out = new Map<string, SentenceEntry[]>();
  const add = (step: string, sentence: string, anchors: CiteAnchor[]) => {
    const list = out.get(step) ?? [];
    let e = list.find((x) => x.sentence === sentence);
    if (!e) {
      e = { sentence, anchors: [] };
      list.push(e);
    }
    for (const a of anchors) if (!e.anchors.some((x) => x.docId === a.docId && x.chunk === a.chunk)) e.anchors.push(a);
    out.set(step, list);
  };
  for (const b of (report?.blocks ?? []) as ReportBlock[]) {
    if (b.kind === "para") b.cites.forEach((c) => add(b.step, c.sentence, c.anchors));
    if (b.kind === "list") b.items.forEach((it) => it.cites.forEach((c) => add(b.step, c.sentence, c.anchors)));
  }
  return out;
}

function AnchorRow({ anchor }: { anchor: CiteAnchor }) {
  const workspaceId = useWorkspaceId();
  const actions = useReportActions();
  const documents = useAtomValue(documentsAtom);
  const [state, setState] = useState<{ status: "loading" | "ok" | "error"; data?: ChunkContext }>({ status: "loading" });
  const [context, setContext] = useState(false);
  const doc = documents.find((d) => d.id === anchor.docId);

  useEffect(() => {
    let cancelled = false;
    getChunk(workspaceId, anchor.docId, anchor.chunk)
      .then((data) => !cancelled && setState({ status: "ok", data }))
      .catch(() => !cancelled && setState({ status: "error" }));
    return () => {
      cancelled = true;
    };
  }, [workspaceId, anchor.docId, anchor.chunk]);

  const d = state.data;
  return (
    <div className="rounded-lg border border-neutral-200 bg-white px-2.5 py-2 text-xs">
      <p className="flex flex-wrap items-baseline gap-x-1.5">
        <span className="font-semibold text-primary">[{anchor.n}]</span>
        <span className="font-medium text-text-primary">{d?.label ?? doc?.label ?? anchor.docId.slice(0, 8)}</span>
        {d?.chunk.page != null && <span className="text-text-secondary">p.{d.chunk.page}</span>}
        {d?.chunk.kind === "table" && <span className="rounded bg-background-gray px-1 text-[10px] text-text-secondary">표</span>}
      </p>
      {state.status === "loading" && <p className="mt-1.5 text-text-secondary">근거 문단을 불러오는 중…</p>}
      {state.status === "error" && <p className="mt-1.5 text-text-secondary italic">{doc ? "문단을 찾지 못했습니다." : "이 자료는 리포트에서 빠졌습니다."}</p>}
      {d && (
        <div className="mt-1.5">
          {d.chunk.heading && <p className="mb-0.5 truncate text-[11px] text-text-secondary">§ {d.chunk.heading}</p>}
          {context && d.prev && <p className="mb-1 leading-5 whitespace-pre-wrap text-text-secondary/80">{d.prev.text}</p>}
          {d.chunk.rows?.length ? (
            <div className="rounded bg-yellow-100/70 p-1">
              <ChunkBody chunk={d.chunk} />
            </div>
          ) : (
            <p className={cn("rounded bg-yellow-100/70 px-1 leading-5 whitespace-pre-wrap text-text-primary", d.chunk.kind === "table" && "font-mono")}>{d.chunk.text}</p>
          )}
          {context && d.next && <p className="mt-1 leading-5 whitespace-pre-wrap text-text-secondary/80">{d.next.text}</p>}
          <div className="mt-1 flex gap-3">
            {(d.prev || d.next) && (
              <button type="button" onClick={() => setContext((v) => !v)} className="cursor-pointer text-[11px] text-primary hover:underline">
                {context ? "앞뒤 문단 접기" : "앞뒤 문단 보기"}
              </button>
            )}
            <button type="button" onClick={() => actions.openDocument(anchor.docId, anchor.chunk)} className="inline-flex cursor-pointer items-center gap-1 text-[11px] text-primary hover:underline">
              <ScrollText className="size-3" aria-hidden />
              문서에서 보기
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SentenceItem({ entry, expanded, tick, onToggle }: { entry: SentenceEntry; expanded: boolean; tick: number; onToggle: () => void }) {
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (expanded) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [expanded, tick]);
  return (
    <li ref={ref} className={cn("rounded-xl border", expanded ? "border-primary-soft-border bg-primary-soft/40" : "border-neutral-200 bg-white")}>
      <button type="button" onClick={onToggle} className="flex w-full cursor-pointer items-start gap-1.5 px-2.5 py-2 text-left">
        {expanded ? <ChevronDown className="mt-0.5 size-3.5 shrink-0 text-text-secondary" aria-hidden /> : <ChevronRight className="mt-0.5 size-3.5 shrink-0 text-text-secondary" aria-hidden />}
        <span className="min-w-0 flex-1">
          <span className={cn("block text-xs leading-5 text-text-primary", !expanded && "line-clamp-2")}>“{entry.sentence}”</span>
          <span className="mt-0.5 block text-[10px] text-text-secondary">출처 {entry.anchors.map((a) => `[${a.n}]`).join(" ")}</span>
        </span>
      </button>
      {expanded && (
        <div className="flex flex-col gap-1.5 px-2.5 pb-2.5">
          {entry.anchors.map((a) => (
            <AnchorRow key={`${a.docId}#${a.chunk}`} anchor={a} />
          ))}
        </div>
      )}
    </li>
  );
}

export const CitationEvidence = memo(function CitationEvidence() {
  const actions = useReportActions();
  const report = useAtomValue(reportAtom);
  const session = useAtomValue(sessionAtom);
  const focus = useAtomValue(evidenceFocusAtom);
  const bySection = useMemo(() => entriesBySection(report), [report]);
  const parts = useMemo(() => (report?.blocks ?? []).filter((b) => b.kind === "heading" && bySection.has(b.step)).map((b) => ({ step: b.step, title: (b as { text: string }).text })), [report, bySection]);
  const [step, setStep] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const active = (step && bySection.has(step) ? step : null) ?? (focus && bySection.has(focus.step) ? focus.step : null) ?? parts[parts.length - 1]?.step ?? null;
  const entries = active ? (bySection.get(active) ?? []) : [];
  const calcs = active ? (session?.evidence?.[active]?.calcs ?? []) : [];

  useEffect(() => {
    if (!focus) return;
    setStep(focus.step);
    setOpen(focus.sentence || null);
  }, [focus]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-neutral-200 px-3 py-2">
        <div className="flex items-center gap-2">
          <p className="min-w-0 flex-1 truncate text-sm font-semibold text-text-primary">출처 근거</p>
          {parts.length > 0 && (
            <select
              aria-label="섹션"
              value={active ?? ""}
              onChange={(e) => {
                setStep(e.target.value);
                setOpen(null);
              }}
              className="h-7 max-w-[55%] truncate rounded-md border border-neutral-200 bg-white px-1.5 text-xs text-text-primary"
            >
              {parts.map((p) => (
                <option key={p.step} value={p.step}>
                  {p.title}
                </option>
              ))}
            </select>
          )}
        </div>
        {active && (
          <p className="mt-1 flex items-center gap-2 text-xs text-text-secondary">
            <span>출처 달린 문장 {entries.length}개</span>
            <button type="button" onClick={() => actions.openSection(active)} className="inline-flex cursor-pointer items-center gap-1 text-primary hover:underline">
              <FileText className="size-3" aria-hidden />
              리포트에서 보기
            </button>
          </p>
        )}
      </div>
      <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {!active && <p className="rounded-lg border border-dashed border-neutral-300 px-3 py-6 text-center text-xs text-text-secondary">아직 출처가 달린 섹션이 없습니다. 섹션을 쓰면 문장마다 근거 문단을 여기서 확인할 수 있습니다.</p>}
        {calcs.length > 0 && (
          <div className="mb-3 rounded-xl border border-sky-200 bg-sky-50/60 px-3 py-2">
            <p className="text-xs font-semibold text-sky-900">코드가 계산한 수치 {calcs.length}건</p>
            {calcs.map((c, i) => (
              <p key={i} className="mt-1 text-xs leading-5 text-text-primary">
                <span className="font-medium">{c.label}</span> = <span className="font-semibold tabular-nums">{c.display}</span>
                <span className="block text-[11px] text-text-secondary">계산식: {c.readable}</span>
              </p>
            ))}
          </div>
        )}
        {active && (
          <ul className="flex flex-col gap-1.5">
            {entries.map((e) => (
              <SentenceItem key={e.sentence} entry={e} expanded={open === e.sentence} tick={focus?.tick ?? 0} onToggle={() => setOpen((cur) => (cur === e.sentence ? null : e.sentence))} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
});
