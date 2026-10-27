"use client";

/**
 * 원문 확인 창 — 가공한 값(원장 칸·표 칸·인용 문단)을 **원본 파일 그대로** 보여 준다(BE app/docs/source_view.py).
 * PDF = 그 쪽 그림 + 강조 상자(문단이 다음 쪽으로 이어지면 쪽마다 — '이어지는 쪽' 버튼), 엑셀 = 원본 시트 격자 + 그 칸, 워드 = 원본 문단·표, 글 = 원본 줄.
 * 위 한 줄 = 가공한 값(비교용). 원본에서 같은 글자를 찾지 못하면 그 쪽만 보이고 '찾지 못했습니다' 한 줄(판정 색 없음).
 */
import { useEffect, useRef, useState } from "react";
import { useAtom } from "jotai";
import { ChevronLeft, ChevronRight, ExternalLink, Loader2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useWorkspaceId } from "../../../workspace/context";
import { documentFileUrl, locateSource, pageImageUrl, type SourceLocation } from "../../api";
import { sourceCheckAtom } from "../../atoms";

const HL = "bg-amber-200/70 ring-2 ring-amber-500";

export function SourceModal() {
  const [target, setTarget] = useAtom(sourceCheckAtom);
  const workspaceId = useWorkspaceId();
  const [loc, setLoc] = useState<SourceLocation | null>(null);
  const [page, setPage] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const markRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!target) return;
    let cancelled = false;
    setLoc(null);
    setError(null);
    setPage(null);
    locateSource(workspaceId, target.docId, target.chunk, target.cell)
      .then((l) => {
        if (cancelled) return;
        setLoc(l);
        if (l.kind === "pdf") setPage(l.page);
      })
      .catch(() => !cancelled && setError("원본 파일을 열지 못했습니다."));
    return () => {
      cancelled = true;
    };
  }, [target, workspaceId]);

  useEffect(() => {
    const t = setTimeout(() => markRef.current?.scrollIntoView({ block: "center" }), 150);
    return () => clearTimeout(t);
  }, [loc, page]);

  useEffect(() => {
    if (!target) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setTarget(null);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [target, setTarget]);

  if (!target) return null;
  const ex = loc?.extracted;
  // 지금 보는 쪽의 상자 — 저장된 쪽별 상자(marks)가 있으면 그것, 없으면 찾은 쪽(loc.page)에만 rects
  const pageRects = loc?.kind === "pdf" && page != null ? (loc.marks ? (loc.marks[String(page)] ?? []) : page === loc.page ? loc.rects : []) : [];
  const markPages = loc?.kind === "pdf" && loc.marks ? Object.keys(loc.marks).map(Number) : [];

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 px-4" onMouseDown={() => setTarget(null)}>
      <div onMouseDown={(e) => e.stopPropagation()} className="flex h-[88vh] w-full max-w-[920px] flex-col overflow-hidden rounded-[20px] bg-white shadow-2xl">
        <div className="flex items-start gap-3 border-b border-neutral-200 px-5 py-3.5">
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-bold text-text-primary">{loc?.label ?? "원문 확인"}</p>
            <p className="truncate text-[12px] text-text-secondary">{[loc?.fileName, loc?.where].filter(Boolean).join(" · ")}</p>
          </div>
          {loc && (
            <a
              href={`${documentFileUrl(workspaceId, loc.docId)}${loc.kind === "pdf" ? `#page=${page ?? loc.page}` : ""}`}
              target="_blank"
              rel="noreferrer"
              className="flex h-8 shrink-0 items-center gap-1 rounded-lg bg-neutral-100 px-2.5 text-[12px] font-semibold text-neutral-700 hover:bg-neutral-200"
            >
              <ExternalLink className="size-3.5" aria-hidden />
              원본 파일
            </a>
          )}
          <button type="button" aria-label="닫기" onClick={() => setTarget(null)} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>

        {ex && (
          <div className="border-b border-neutral-100 bg-neutral-50 px-5 py-2 text-[13px] text-text-primary">
            <span className="mr-2 text-[12px] font-semibold text-text-secondary">가공한 값</span>
            {"text" in ex ? (
              <span className="text-text-secondary">{ex.text}</span>
            ) : (
              <>
                <span className="font-semibold tabular-nums">{ex.display}</span>
                {ex.metric && <span className="ml-2 text-text-secondary">{[ex.metric, ex.period].filter(Boolean).join(" · ")}</span>}
              </>
            )}
          </div>
        )}
        {loc && !loc.found && target.chunk && <p className="border-b border-neutral-100 px-5 py-2 text-[13px] text-text-secondary">이 {loc.kind === "pdf" ? "쪽" : loc.kind === "sheet" ? "시트" : "부분"}에서 같은 글자를 찾지 못했습니다.</p>}

        <div className="thin-scrollbar min-h-0 flex-1 overflow-auto bg-neutral-100/60 px-5 py-4">
          {error && <p className="py-10 text-center text-[14px] text-red-600">{error}</p>}
          {!loc && !error && (
            <p className="flex items-center justify-center gap-2 py-16 text-[13px] text-text-secondary">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              원본 파일을 여는 중
            </p>
          )}

          {loc?.kind === "pdf" && page != null && (
            <div className="mx-auto w-full max-w-[760px]">
              <div className="relative w-full bg-white shadow-sm" style={{ aspectRatio: `1 / ${loc.ratio}` }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={pageImageUrl(workspaceId, loc.docId, page)} alt={`${page}쪽`} className="absolute inset-0 h-full w-full" />
                {pageRects.map(([x0, y0, x1, y1], i) => (
                    <span
                      key={i}
                      ref={i === 0 ? (el) => void (markRef.current = el) : undefined}
                      className="absolute rounded-sm bg-amber-300/35 ring-2 ring-amber-500"
                      style={{ left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` }}
                    />
                  ))}
              </div>
              {markPages.length > 1 && (
                <div className="mt-3 flex items-center justify-center gap-1.5 text-[12px] text-text-secondary">
                  이어지는 쪽
                  {markPages.map((p) => (
                    <button key={p} type="button" onClick={() => setPage(p)} className={cn("cursor-pointer rounded-md px-2 py-0.5 font-semibold", p === page ? "bg-amber-100 text-amber-800" : "bg-white text-neutral-700 hover:bg-neutral-50")}>
                      p.{p}
                    </button>
                  ))}
                </div>
              )}
              {loc.pages > 1 && (
                <div className="mt-3 flex items-center justify-center gap-3 text-[13px] text-text-secondary">
                  <button type="button" aria-label="앞 쪽" disabled={page <= 1} onClick={() => setPage(page - 1)} className="cursor-pointer rounded-lg p-1 hover:bg-white disabled:opacity-30">
                    <ChevronLeft className="size-4" aria-hidden />
                  </button>
                  <span className="tabular-nums">
                    {page} / {loc.pages}
                  </span>
                  <button type="button" aria-label="다음 쪽" disabled={page >= loc.pages} onClick={() => setPage(page + 1)} className="cursor-pointer rounded-lg p-1 hover:bg-white disabled:opacity-30">
                    <ChevronRight className="size-4" aria-hidden />
                  </button>
                </div>
              )}
            </div>
          )}

          {loc?.kind === "sheet" && (
            <div className="overflow-auto rounded-lg bg-white shadow-sm">
              <table className="border-collapse text-[12px] tabular-nums">
                <thead>
                  <tr>
                    <th className="sticky top-0 border border-neutral-200 bg-neutral-100 px-2 py-1" />
                    {loc.cols.map((c) => (
                      <th key={c} className="sticky top-0 border border-neutral-200 bg-neutral-100 px-2 py-1 font-medium text-neutral-500">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loc.grid.map((row, r) => {
                    const rowHl = loc.hl.some(([hr, hc]) => hr === r && hc === -1);
                    return (
                      <tr key={r}>
                        <td className="border border-neutral-200 bg-neutral-100 px-2 py-1 text-right text-neutral-500">{loc.rowNums[r]}</td>
                        {row.map((v, c) => {
                          const on = loc.hl.some(([hr, hc]) => hr === r && hc === c);
                          return (
                            <td
                              key={c}
                              ref={on ? (el) => void (markRef.current = el) : undefined}
                              className={cn("border border-neutral-200 px-2 py-1 whitespace-nowrap", on ? HL : rowHl && "bg-amber-100/70")}
                            >
                              {v}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {loc?.kind === "docx" && (
            <div className="mx-auto flex max-w-[760px] flex-col gap-2 rounded-lg bg-white px-6 py-5 shadow-sm">
              {loc.blocks.map((b, i) =>
                b.type === "p" ? (
                  <p key={i} ref={loc.at === i ? (el) => void (markRef.current = el) : undefined} className={cn("rounded px-1 text-[13px] leading-6", loc.at === i && !loc.cell && HL)}>
                    {b.text}
                  </p>
                ) : (
                  <table key={i} className="border-collapse text-[12px]">
                    <tbody>
                      {b.rows.map((row, r) => (
                        <tr key={r}>
                          {row.map((v, c) => {
                            const on = loc.at === i && loc.cell?.[0] === r && loc.cell?.[1] === c;
                            return (
                              <td key={c} ref={on ? (el) => void (markRef.current = el) : undefined} className={cn("border border-neutral-300 px-2 py-1", on ? HL : loc.at === i && !loc.cell && "bg-amber-100/70")}>
                                {v}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ),
              )}
            </div>
          )}

          {loc?.kind === "text" && (
            <div className="mx-auto max-w-[760px] rounded-lg bg-white py-3 shadow-sm">
              {loc.lines.map((l, i) => {
                const on = loc.hl.includes(i);
                return (
                  <div key={i} ref={on && i === loc.hl[0] ? (el) => void (markRef.current = el) : undefined} className={cn("flex gap-3 px-4 py-0.5 font-mono text-[12px] leading-5", on && "bg-amber-100/80")}>
                    <span className="w-8 shrink-0 text-right text-neutral-400">{loc.lineNums[i]}</span>
                    <span className="whitespace-pre-wrap text-text-primary">{l || " "}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
