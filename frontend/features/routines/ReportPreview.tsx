"use client";

/**
 * 루틴이 쓴 문서 미리보기(읽기 전용) — 문서 화면(Studio) 밖에서 그린다. 표·차트는 문서 화면과 같은 부품(TableBlockView·ChartBlockView), 숫자를 누르면 원문 창.
 * 양식 2.0 요약 파트의 사이드바 블록(position sidebar)이 있으면 원본처럼 2단(왼쪽 본문·표, 오른쪽 차트·점검표)으로 놓는다.
 */
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getSession } from "../report/api";
import { ChartBlockView, TableBlockView } from "../report/components/report/FormatBlock";
import type { ReportBlock, ReportSource, ReportView } from "../report/types";
import { useOpenSource } from "../workspace/sourceHost";

/** 본문의 출처 표지 '[1, 2]' → 위 첨자 */
function cited(text: string) {
  return text.split(/(\[\d+(?:,\s*\d+)*\])/g).map((t, i) =>
    /^\[\d/.test(t) ? (
      <sup key={i} className="ml-0.5 text-[9px] font-bold text-primary">
        {t}
      </sup>
    ) : (
      t
    ),
  );
}

function Block({ b }: { b: ReportBlock }) {
  const open = useOpenSource();
  switch (b.kind) {
    case "table":
      return <TableBlockView block={b} onOpen={open} />;
    case "chart":
      return <ChartBlockView block={b} onOpen={open} />;
    case "subhead":
      return <h3 className="mt-3 mb-1 border-l-[3px] pl-2 text-[13px] font-bold text-text-primary" style={{ borderColor: "var(--doc-accent, #2E75B6)" }}>{b.text}</h3>;
    case "heading":
      return b.role === "summary" ? null : <h3 className="mt-4 mb-1 text-[14px] font-bold text-text-primary">{b.text}</h3>;
    case "para":
      return <p className={b.role === "claim" ? "mt-2 text-[13px] font-bold text-text-primary" : "mt-1 text-[12.5px] leading-[1.65] text-neutral-800"}>{cited(b.text)}</p>;
    case "list":
      return (
        <ul className="mt-1 flex flex-col gap-1.5">
          {b.items.map((it, i) => (
            <li key={i} className="flex gap-1.5 text-[12.5px] leading-[1.6] text-neutral-800">
              <span className="mt-[7px] size-1 shrink-0 rounded-full bg-neutral-500" aria-hidden />
              <span>{cited(it.text)}</span>
            </li>
          ))}
        </ul>
      );
    default:
      return null;
  }
}

export function ReportPreview({ reportId, onLoaded }: { reportId: string; onLoaded?: (sources: ReportSource[], stats: ReportView["stats"]) => void }) {
  const [view, setView] = useState<ReportView | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    setView(null);
    setFailed(false);
    getSession(reportId).then(
      (p) => {
        if (!live) return;
        setView(p.report);
        onLoaded?.(p.report.sources, p.report.stats);
      },
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [reportId]); // eslint-disable-line react-hooks/exhaustive-deps
  if (failed) return <p className="py-10 text-center text-[13px] text-text-secondary">문서를 불러오지 못했습니다.</p>;
  if (!view) return <Loader2 className="mx-auto my-16 size-5 animate-spin text-neutral-400" aria-hidden />;
  const blocks = view.blocks.filter((b) => b.kind !== "empty" && b.kind !== "band");
  const isSide = (b: ReportBlock) => (b.kind === "table" || b.kind === "chart" || b.kind === "figure") && b.position === "sidebar";
  const side = blocks.filter(isSide);
  const main = blocks.filter((b) => !isSide(b));
  const accent = view.theme?.accent ?? "#1F3A5F";
  return (
    <article className="rounded-xl border border-neutral-200 bg-white" style={{ ["--doc-accent" as string]: accent }}>
      <header className="flex items-baseline justify-between gap-3 rounded-t-xl px-4 py-2.5 text-white" style={{ background: accent }}>
        <h2 className="truncate text-[14px] font-bold">{view.title}</h2>
        <span className="shrink-0 text-[11px] opacity-90">{view.subtitle.split(" · ")[0]}</span>
      </header>
      <div className={side.length ? "grid grid-cols-1 gap-x-5 px-4 py-3 xl:grid-cols-[1.3fr_1fr]" : "px-4 py-3"}>
        <div className="min-w-0 [&_table]:text-[11.5px] [&_td]:!px-1 [&_td]:!py-[5px] [&_td]:whitespace-nowrap [&_th]:!px-1">
          {main.map((b, i) => (
            <Block key={i} b={b} />
          ))}
        </div>
        {side.length > 0 && (
          <div className="min-w-0 [&_table]:text-[11.5px] [&_td]:!px-1.5 [&_td]:!py-[5px] [&_th]:!px-1.5">
            {side.map((b, i) => (
              <Block key={i} b={b} />
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
