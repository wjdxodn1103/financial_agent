"use client";

/**
 * 리포트 블록 하나 — BE 가 조립한 ReportView.blocks 를 그대로 그린다(OP-FE BlockView 와 같은 원칙: 토큰을 파싱하지 않는다).
 * 출처 표기 `[n]` 은 BE 가 준 위치(cites)로 버튼이 되고, 누르면 오른쪽 "근거" 탭에 그 문장의 근거 문단이 열린다.
 * 원본 칸·계산식에 이어진 숫자(LINKED_NUMBER)만 옅은 밑줄이 붙고, 누르면 오른쪽 "숫자 출처" 탭에 그 숫자의 원본 칸이 열린다.
 * 이어지지 않은 숫자는 그냥 글자다 — 판정 색·문구는 본문에 싣지 않는다.
 */
import { Fragment, useState, type ReactNode } from "react";
import { useAtomValue } from "jotai";
import { BarChart3, LayoutTemplate, PenLine, Table2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { canChatAtom, reportAtom } from "../../atoms";
import { LINKED_NUMBER } from "../../constants";
import { useReportActions } from "../../hooks/useReportStudio";
import type { CitationSpan, NumberSpan, ReportBlock } from "../../types";
import { ChartBlockView, TableBlockView } from "./FormatBlock";

type Seg = { start: number; end: number; cite?: CitationSpan; num?: NumberSpan };

function CitedText({ text, cites, nums, step, activeKey }: { text: string; cites: CitationSpan[]; nums: NumberSpan[]; step: string; activeKey?: string }) {
  const actions = useReportActions();
  const segs: Seg[] = [
    ...cites.map((c) => ({ start: c.start, end: c.end, cite: c })),
    ...nums.filter((n) => LINKED_NUMBER.has(n.status) && text.slice(n.start, n.end) === n.raw).map((n) => ({ start: n.start, end: n.end, num: n })),
  ].sort((a, b) => a.start - b.start);
  if (!segs.length) return <>{text}</>;
  const parts: ReactNode[] = [];
  let pos = 0;
  segs.forEach((s, i) => {
    if (s.start < pos || s.end > text.length || s.end <= s.start) return;
    parts.push(<Fragment key={`t${i}`}>{text.slice(pos, s.start)}</Fragment>);
    if (s.cite) {
      const c = s.cite;
      parts.push(
        <button
          key={`c${i}`}
          type="button"
          title="근거 문단 보기"
          onClick={() => actions.openCitation(step, c.sentence)}
          className="cursor-pointer rounded-sm align-super text-[0.7em] font-semibold text-primary transition-colors hover:bg-primary-soft"
        >
          {text.slice(c.start, c.end)}
        </button>,
      );
    } else if (s.num) {
      const n = s.num;
      parts.push(
        <button
          key={`n${i}`}
          type="button"
          data-num={n.key}
          title="원본 보기"
          onClick={() => actions.openNumber(n.key)}
          className={cn(
            "cursor-pointer rounded-[2px] underline decoration-primary/30 decoration-1 underline-offset-[3px] transition-colors hover:bg-primary-soft hover:decoration-primary",
            n.key === activeKey && "bg-primary-soft decoration-primary",
          )}
        >
          {text.slice(n.start, n.end)}
        </button>,
      );
    }
    pos = s.end;
  });
  parts.push(<Fragment key="tail">{text.slice(pos)}</Fragment>);
  return <>{parts}</>;
}

/**
 * 섹션의 '표·차트 넣기' — 이 문서 양식의 표·차트 양식(샘플로 만든 양식)을 고르면 문서 작성 모드로 바꾸고 입력창에 부탁을 적어 둔다.
 * 사용자가 대상(행)·자료를 덧붙여 보내면 AI 가 insert_form 으로 만들어 이 섹션 뒤에 넣는다(행을 모르면 묻는다).
 */
function FormInsert({ section }: { section: string }) {
  const forms = useAtomValue(reportAtom)?.forms ?? [];
  const canChat = useAtomValue(canChatAtom);
  const actions = useReportActions();
  const [open, setOpen] = useState(false);
  if (!forms.length || !canChat) return null;
  return (
    <span className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-dashed border-neutral-300 px-2 py-0.5 text-[11px] font-normal text-text-secondary transition-colors hover:border-primary hover:text-primary"
      >
        <Table2 className="size-3.5" aria-hidden />
        표·차트 넣기
      </button>
      {open && (
        <div className="absolute top-full left-0 z-30 mt-1 w-[320px] rounded-xl bg-white p-1.5 text-left shadow-[0_8px_24px_rgba(0,27,55,0.16)]" onMouseLeave={() => setOpen(false)}>
          {forms.map((f) => {
            const Icon = f.kind === "chart" ? BarChart3 : Table2;
            return (
              <button
                key={f.id}
                type="button"
                title={f.desc}
                onClick={() => {
                  setOpen(false);
                  actions.setModes({ research: false, writing: true });
                  actions.draft(`'${f.name}' 양식으로 '${section}' 섹션에 넣을 ${f.kind === "chart" ? "차트" : "표"} 만들어줘 — `);
                }}
                className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] font-normal text-text-primary hover:bg-neutral-100"
              >
                <Icon className="size-4 shrink-0 text-primary" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{f.name}</span>
              </button>
            );
          })}
        </div>
      )}
    </span>
  );
}

export function BlockView({ block, focused, nums = [], activeKey }: { block: ReportBlock; focused: boolean; nums?: NumberSpan[]; activeKey?: string }) {
  const actions = useReportActions();
  switch (block.kind) {
    case "band":
      // 양식 2.0 장 띠 — 테마 띠 색 칸에 흰 글자(원본 KIRS 처럼), 부록은 제목만
      return block.band ? (
        <div className="clear-both mt-10 mb-1">
          <span className="inline-block px-5 py-1 text-[15px] font-bold" style={{ background: "var(--doc-band, #1F3A5F)", color: "var(--doc-band-text, #fff)" }}>
            {block.text}
          </span>
        </div>
      ) : (
        <h2 className="clear-both mt-10 border-b-2 pb-1 text-base font-bold text-text-primary" style={{ borderColor: "var(--doc-accent, #1F3A5F)" }}>
          {block.text}
        </h2>
      );
    case "subhead":
      // 양식 2.0 소주제 안 작은 제목('### …' 줄)
      return <h4 className="mt-4 mb-1 text-[13px] font-bold text-text-primary">{block.text}</h4>;
    case "figure":
      return (
        <div className="my-2 rounded border border-dashed border-neutral-300 px-3 py-1.5 text-[11px] text-neutral-400" title="원본 양식의 그림 자리 — 자료를 넣으면 채울 수 있습니다">
          {block.note ? "참고" : "그림 자리"} · {block.title}
        </div>
      );
    case "heading":
      if (block.depth === 2) {
        // 양식 2.0 소제목 — 강조색·번호(원본의 번호 아이콘)
        return (
          <h3 data-step={block.step} className={cn("group clear-both mt-7 flex scroll-mt-4 items-baseline gap-2 text-[15px] font-bold", focused && "underline")} style={{ color: "var(--doc-accent, #1F3A5F)" }}>
            {block.no != null && (
              <span className="inline-flex size-[18px] shrink-0 items-center justify-center self-center text-[11px] text-white" style={{ background: "var(--doc-accent, #1F3A5F)" }}>
                {block.no}
              </span>
            )}
            <span className="min-w-0 flex-1">{block.text}</span>
            {block.status === "written" && (
              <span className="opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                <FormInsert section={block.text} />
              </span>
            )}
          </h3>
        );
      }
      return (
        <h2 data-step={block.step} className={cn("group clear-both mt-7 flex scroll-mt-4 items-baseline gap-2 border-b border-neutral-200 pb-1.5 text-base font-bold text-text-primary", focused && "text-primary")}>
          <span className="min-w-0 flex-1">{block.text}</span>
          {block.status === "written" && (
            <span className="opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
              <FormInsert section={block.text} />
            </span>
          )}
        </h2>
      );
    case "para":
      if (block.role === "claim") {
        // 요약 주장 — 강조색 굵게(원본 요약 쪽의 빨간 주장 줄)
        return (
          <p data-step={block.step} className="mt-5 text-[14px] leading-6 font-bold" style={{ color: "var(--doc-accent, #1F3A5F)" }}>
            <CitedText text={block.text} cites={block.cites} nums={nums.filter((n) => n.i === null)} step={block.step} activeKey={activeKey} />
          </p>
        );
      }
      if (block.role === "keyline") {
        // 핵심 문장 — 본문 왼쪽 칸(원본의 굵은 요지 줄), 다음 문단이 오른쪽으로 흐른다
        return (
          <p data-step={block.step} className="float-left mt-2.5 mr-5 w-[27%] text-[12.5px] leading-6 font-bold whitespace-pre-wrap text-text-primary">
            <CitedText text={block.text} cites={block.cites} nums={nums.filter((n) => n.i === null)} step={block.step} activeKey={activeKey} />
          </p>
        );
      }
      return (
        <p data-step={block.step} className={cn("chat-prose mt-2.5 text-sm leading-7 whitespace-pre-wrap text-text-primary", focused && "-mx-3 rounded-lg bg-primary-soft px-3 py-1")}>
          <CitedText text={block.text} cites={block.cites} nums={nums.filter((n) => n.i === null)} step={block.step} activeKey={activeKey} />
        </p>
      );
    case "list":
      return (
        <ul data-step={block.step} className={cn("chat-prose mt-2.5 list-disc space-y-1 pl-5 text-sm leading-7 text-text-primary", focused && "-mx-3 rounded-lg bg-primary-soft px-3 py-1 pl-8")}>
          {block.items.map((it, i) => (
            <li key={i}>
              <CitedText text={it.text} cites={it.cites} nums={nums.filter((n) => n.i === i)} step={block.step} activeKey={activeKey} />
            </li>
          ))}
        </ul>
      );
    case "empty":
      return (
        <>
          <button
          type="button"
          data-step={block.step}
          title={block.desc || undefined}
          onClick={() => actions.draft(`${block.title} 써줘`)}
          className="mt-2 inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-dashed border-neutral-300 px-2.5 py-1 text-xs text-text-secondary transition-colors hover:border-primary hover:text-primary"
        >
          <PenLine className="size-3.5" aria-hidden />이 섹션 쓰기
          </button>
          <span className="mt-2 ml-1.5 inline-block align-top">
            <FormInsert section={block.title} />
          </span>
          {/* 등록 양식의 표·차트 자리 — 누르면 채워 달라는 말이 입력창에 */}
          {block.slots?.some((x) => x.kind !== "figure") && (
            <button
              type="button"
              title={block.slots.map((x) => x.title).join(", ")}
              onClick={() => actions.draft(`${block.title} 섹션의 표·차트 자리를 채워줘`)}
              className="mt-2 ml-1.5 inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-dashed border-primary-soft-border px-2.5 py-1 text-xs text-primary transition-colors hover:border-primary"
            >
              <LayoutTemplate className="size-3.5" aria-hidden />
              {block.slots.filter((x) => x.kind !== "figure").map((x) => x.title).join(" · ")} 채우기
            </button>
          )}
        </>
      );
    case "table":
      return block.insertedId ? <InsertedTable block={block} /> : <TableBlockView block={block} />;
    case "chart":
      return block.insertedId ? <InsertedTable block={block} /> : <ChartBlockView block={block} />;
    default:
      return null;
  }
}

/** 리서치에서 넣은 표·차트 — 작성자는 빼기 버튼으로 뺀다 */
function InsertedTable({ block }: { block: Extract<ReportBlock, { kind: "table" | "chart" }> }) {
  const actions = useReportActions();
  const canChat = useAtomValue(canChatAtom);
  const what = block.kind === "chart" ? "차트" : "표";
  return (
    <div className="group relative">
      {block.kind === "chart" ? <ChartBlockView block={block} /> : <TableBlockView block={block} />}
      {canChat && (
        <button
          type="button"
          title={`${what} 빼기`}
          aria-label={`${what} 빼기`}
          onClick={() => window.confirm(`이 ${what}를 문서에서 뺄까요?`) && void actions.removeTable(block.step, block.insertedId!)}
          className="absolute top-4 right-0 cursor-pointer rounded-md p-1 text-neutral-400 opacity-0 group-hover:opacity-100 hover:bg-neutral-100 hover:text-neutral-700"
        >
          <X className="size-4" aria-hidden />
        </button>
      )}
    </div>
  );
}
