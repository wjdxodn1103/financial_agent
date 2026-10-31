"use client";

/**
 * 원문 확인 창 — 가공한 값(원장 칸·표 칸·인용 문단)을 **원본 파일 그대로** 보여 준다(BE app/docs/source_view.py).
 * PDF = 그 쪽 그림 + 강조 상자(문단이 다음 쪽으로 이어지면 쪽마다 — '이어지는 쪽' 버튼), 엑셀 = 원본 시트 격자 + 그 칸, 워드 = 원본 문단·표, 글 = 원본 줄.
 * 위 한 줄 = 가공한 값(비교용). 원본에서 같은 글자를 찾지 못하면 그 쪽만 보이고 '찾지 못했습니다' 한 줄(판정 색 없음).
 * 연결 스냅샷(DART 등 API 로 받은 JSON) = 그 시트 표 + 그 칸(근거 카드에서 열면 문장 속 금액과 같은 칸) + 그 값이 나온 API 응답 항목,
 * 위쪽에 연결 이름·조회 시각과 [DART 공시 원문] — 원본 JSON 은 [받은 원본(JSON)] 으로만.
 */
import { useEffect, useRef, useState } from "react";
import { useAtom } from "jotai";
import { ChevronLeft, ChevronRight, ExternalLink, Loader2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useWorkspaceId } from "../../../workspace/context";
import { documentFileUrl, locateSource, pageImageUrl, type SourceLocation } from "../../api";
import { sourceCheckAtom } from "../../atoms";

const HL = "bg-amber-200/70 ring-2 ring-amber-500";

export type SourceTarget = { docId: string; chunk?: string | null; cell?: [number, number] | null; quote?: string | null; tick?: number };

/** 조회 시각(UTC ISO) → 한국 시각 'YYYY-MM-DD HH:MM' */
function kst(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t + 9 * 3600 * 1000).toISOString().slice(0, 16).replace("T", " ");
}

/** Studio 의 원문 확인 창(스튜디오 atom) — 그리는 몸통은 SourceDialog 하나를 드라이브·검색·대시보드도 같이 쓴다 */
export function SourceModal() {
  const [target, setTarget] = useAtom(sourceCheckAtom);
  if (!target) return null;
  return <SourceDialog target={target} onClose={() => setTarget(null)} />;
}

export function SourceDialog({ target, onClose }: { target: SourceTarget; onClose: () => void }) {
  const setTarget = (_: null) => onClose();
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
    locateSource(workspaceId, target.docId, target.chunk, target.cell, target.quote)
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
    const t = setTimeout(() => {
      const el = markRef.current;
      // 스냅샷 표는 표 상자만 움직인다(바깥 창까지 움직이면 위의 API 응답 항목이 밀려난다)
      const box = loc?.kind === "snapshot" ? (el?.closest("[data-scroll-box]") as HTMLElement | null) : null;
      if (el && box) {
        box.scrollTop += el.getBoundingClientRect().top - box.getBoundingClientRect().top - box.clientHeight / 2;
        el.scrollIntoView({ block: "nearest" }); // 표가 짧아 상자가 안 움직이면 바깥 창을 그 칸이 보일 만큼만
      } else el?.scrollIntoView({ block: "center" });
    }, 150);
    return () => clearTimeout(t);
  }, [loc, page]);

  useEffect(() => {
    if (!target) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setTarget(null);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [target, setTarget]);

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
            <p className="truncate text-[12px] text-text-secondary">
              {loc?.origin
                ? [`${loc.origin.name}에서 ${kst(loc.origin.fetchedAt)}에 받음`, loc.where].filter(Boolean).join(" · ")
                : [loc?.fileName, loc?.where].filter(Boolean).join(" · ")}
            </p>
          </div>
          {loc?.origin?.url && (
            <a
              href={loc.origin.url}
              target="_blank"
              rel="noreferrer"
              className="flex h-8 shrink-0 items-center gap-1 rounded-lg bg-primary px-2.5 text-[12px] font-semibold text-white hover:bg-primary/90"
            >
              <ExternalLink className="size-3.5" aria-hidden />
              {loc.origin.urlLabel}
            </a>
          )}
          {loc && (
            <a
              href={`${documentFileUrl(workspaceId, loc.docId)}${loc.kind === "pdf" ? `#page=${page ?? loc.page}` : ""}`}
              target="_blank"
              rel="noreferrer"
              className="flex h-8 shrink-0 items-center gap-1 rounded-lg bg-neutral-100 px-2.5 text-[12px] font-semibold text-neutral-700 hover:bg-neutral-200"
            >
              <ExternalLink className="size-3.5" aria-hidden />
              {loc.kind === "snapshot" ? "받은 원본(JSON)" : "원본 파일"}
            </a>
          )}
          <button type="button" aria-label="닫기" onClick={() => setTarget(null)} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>

        {ex && (
          <div className="border-b border-neutral-100 bg-neutral-50 px-5 py-2 text-[13px] text-text-primary">
            <span className="mr-2 text-[12px] font-semibold text-text-secondary">{"text" in ex && ex.quote ? "인용한 문장" : "가공한 값"}</span>
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
        {loc?.anchorStatus === "relocated" && <p className="border-b border-neutral-100 px-5 py-2 text-[13px] text-text-secondary">원문이 바뀌어 저장할 때의 글자로 다시 찾았습니다.</p>}
        {loc?.anchorStatus === "missing" && loc.pinned && (
          <p className="border-b border-neutral-100 px-5 py-2 text-[13px] text-text-secondary">
            지금 원문에서 찾지 못했습니다 · 저장 당시: “{(loc.pinned.value?.raw ? `${loc.pinned.rowLabel ?? ""} ${loc.pinned.value.raw}` : loc.pinned.quote ?? "").slice(0, 140)}”
          </p>
        )}
        {loc && !loc.found && target.chunk && loc.anchorStatus !== "missing" && <p className="border-b border-neutral-100 px-5 py-2 text-[13px] text-text-secondary">이 {loc.kind === "pdf" ? "쪽" : loc.kind === "sheet" ? "시트" : "부분"}에서 같은 글자를 찾지 못했습니다.</p>}

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

          {loc?.kind === "snapshot" && loc.table && (
            <div className="flex flex-col gap-3">
              {loc.record && loc.record.length > 0 && (
                <div className="rounded-lg bg-white px-4 py-3 shadow-sm">
                  <p className="mb-2 text-[12px] font-semibold text-text-secondary">
                    {loc.recordOf && <span className="mr-1.5 text-text-primary">{loc.recordOf}</span>}이 값이 나온 API 응답 항목
                  </p>
                  <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-4 gap-y-1 text-[12px]">
                    {loc.record.map((f) => (
                      <div key={f.key} className={cn("flex min-w-0 items-baseline gap-2 rounded px-1.5 py-0.5", f.on && HL)}>
                        <dt className="shrink-0 text-text-secondary" title={f.key}>
                          {f.name || f.key}
                        </dt>
                        <dd className="min-w-0 truncate font-medium text-text-primary tabular-nums" title={f.value}>
                          {f.value}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
              <div className="rounded-lg bg-white shadow-sm">
                <p className="flex items-baseline gap-2 border-b border-neutral-100 px-3 py-2 text-[13px] font-semibold text-text-primary">
                  {loc.table.title}
                  {loc.table.unit && <span className="text-[11px] font-normal text-text-secondary">(단위: {loc.table.unit})</span>}
                </p>
                {/* 표가 자기 상자 안에서 스크롤 — 강조 칸으로 내려가도 머리(기간 열)가 위에 붙어 있다 */}
                <div data-scroll-box className="thin-scrollbar max-h-[56vh] overflow-auto">
                  <table className="w-full border-collapse text-[12px] tabular-nums">
                    <thead>
                      <tr>
                        {loc.table.header.map((h, c) => (
                          <th key={c} className={cn("sticky top-0 border-b border-neutral-200 bg-neutral-50 px-3 py-1.5 font-semibold whitespace-nowrap text-neutral-600", c === 0 ? "text-left" : "text-right")}>
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {loc.table.rows.map((row, r) => {
                        const rowOn = (loc.hl ?? []).some(([hr]) => hr === r);
                        return (
                          <tr key={r} className={cn("border-b border-neutral-100", rowOn && "bg-amber-50")}>
                            {row.map((v, c) => {
                              const on = (loc.hl ?? []).some(([hr, hc]) => hr === r && hc === c);
                              // 스크롤은 문장 순서의 첫 칸으로(맨 아래 칸으로 가면 위의 API 응답 항목이 밀려난다)
                              const first = loc.hl?.[0]?.[0] === r && loc.hl?.[0]?.[1] === c;
                              return (
                                <td
                                  key={c}
                                  ref={first ? (el) => void (markRef.current = el) : undefined}
                                  className={cn("px-3 py-1 whitespace-nowrap", c === 0 ? "text-left text-text-primary" : "text-right", on && HL)}
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
              </div>
            </div>
          )}

          {loc?.kind === "snapshot" && loc.blocks && (
            <div className="mx-auto flex max-w-[760px] flex-col gap-2 rounded-lg bg-white px-6 py-5 shadow-sm">
              {loc.blocks.map((b, i) =>
                b.type === "p" ? (
                  <p key={i} ref={loc.at === i ? (el) => void (markRef.current = el) : undefined} className={cn("rounded px-1 text-[13px] leading-6", loc.at === i && HL)}>
                    {b.text}
                  </p>
                ) : (
                  <table key={i} ref={loc.at === i ? (el) => void (markRef.current = el) : undefined} className={cn("border-collapse text-[12px]", loc.at === i && "ring-2 ring-amber-500")}>
                    <tbody>
                      {b.rows.map((row, r) => (
                        <tr key={r}>
                          {row.map((v, c) => (
                            <td key={c} className={cn("border border-neutral-300 px-2 py-1", loc.at === i && "bg-amber-50")}>
                              {v}
                            </td>
                          ))}
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
