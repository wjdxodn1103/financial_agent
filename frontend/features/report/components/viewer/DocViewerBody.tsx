"use client";

/**
 * 문서 한 편의 문단을 **스크롤하며 불러온다**(지연 로딩: 30문단씩, 바닥 감지 IntersectionObserver).
 * 특정 문단(focus)으로 오면 그 문단이 든 페이지부터 불러와 강조·스크롤한다(앞부분은 "앞 문단 더 보기").
 * 리포트 스튜디오의 "보기" 탭과 워크스페이스 "데이터 업로드" 화면이 같이 쓴다 — 상태는 props 로만 받는다.
 * 머리에는 제목·업로드 시점·크기·원본 링크만(문단 수·카드 정리 같은 처리 정보는 보이지 않는다).
 */
import { memo, useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, Loader2, Table2 } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { docTableAsset } from "../../../research/api";
import { FEATURES } from "../../../workspace/features";
import { ApiError, documentFileUrl, getChunk, getChunks } from "../../api";
import { useMaybeReportActions } from "../../hooks/useReportStudio";
import type { DocChunk, DocumentCard } from "../../types";
import { fileMeta } from "../library/rows";
import { ChunkBody } from "./ChunkBody";

const PAGE = 30;

export const DocViewerBody = memo(function DocViewerBody({
  workspaceId,
  doc,
  focusChunk,
  focusCell,
  tick,
}: {
  workspaceId: string;
  doc: DocumentCard;
  focusChunk?: string;
  /** 원장에서 온 경우 표의 칸 [행, 열] */
  focusCell?: [number, number] | null;
  tick?: number;
}) {
  const [chunks, setChunks] = useState<DocChunk[]>([]);
  const [range, setRange] = useState<{ start: number; end: number; total: number }>({ start: 0, end: 0, total: 0 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const reqRef = useRef(0);
  const actions = useMaybeReportActions();
  const [making, setMaking] = useState<string | null>(null);

  // 표 [에셋으로] — 칸 = 원문 칸(LLM 없음). 작업 화면이면 그 작업의 에셋으로 바로 연다
  const toAsset = async (chunk: string) => {
    setMaking(chunk);
    try {
      const t = await docTableAsset(workspaceId, doc.id, chunk);
      if (actions) actions.attachAsset(t);
      toast.success(actions ? "에셋으로 꺼냈습니다." : "내 에셋에 넣었습니다(드라이브 ▸ 에셋).", { position: "top-center" });
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "꺼내지 못했습니다.", { position: "top-center" });
    } finally {
      setMaking(null);
    }
  };

  // 문서·포커스가 바뀌면 처음부터 — 포커스 문단이 있으면 그 문단 몇 칸 앞부터
  useEffect(() => {
    const seq = ++reqRef.current;
    setChunks([]);
    setError(null);
    setLoading(true);
    (async () => {
      try {
        let start = 0;
        if (focusChunk) {
          const ctx = await getChunk(workspaceId, doc.id, focusChunk);
          start = Math.max(0, (ctx.chunk.index ?? 0) - 3);
        }
        const page = await getChunks(workspaceId, doc.id, start, PAGE);
        if (seq !== reqRef.current) return;
        setChunks(page.chunks);
        setRange({ start, end: start + page.chunks.length, total: page.total });
      } catch {
        if (seq === reqRef.current) setError("문서를 불러오지 못했습니다.");
      } finally {
        if (seq === reqRef.current) setLoading(false);
      }
    })();
  }, [workspaceId, doc.id, focusChunk, tick]);

  const loadMore = useCallback(
    async (dir: "next" | "prev") => {
      if (loading) return;
      const offset = dir === "next" ? range.end : Math.max(0, range.start - PAGE);
      const limit = dir === "next" ? PAGE : range.start - offset;
      if ((dir === "next" && range.end >= range.total) || limit <= 0) return;
      const seq = reqRef.current;
      setLoading(true);
      try {
        const page = await getChunks(workspaceId, doc.id, offset, limit);
        if (seq !== reqRef.current) return;
        setChunks((cur) => (dir === "next" ? [...cur, ...page.chunks] : [...page.chunks, ...cur]));
        setRange((r) => (dir === "next" ? { ...r, end: r.end + page.chunks.length, total: page.total } : { ...r, start: offset, total: page.total }));
      } catch {
        setError("더 불러오지 못했습니다.");
      } finally {
        setLoading(false);
      }
    },
    [doc.id, loading, range, workspaceId],
  );

  // 바닥에 닿으면 다음 페이지
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && void loadMore("next"), { root: listRef.current, rootMargin: "200px" });
    io.observe(el);
    return () => io.disconnect();
  }, [loadMore]);

  // 포커스 문단으로 스크롤
  useEffect(() => {
    if (!focusChunk || !chunks.length) return;
    listRef.current?.querySelector<HTMLElement>(`[data-chunk="${focusChunk}"]`)?.scrollIntoView({ block: "center" });
  }, [chunks.length, focusChunk, tick]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-start justify-between gap-3 border-b border-neutral-200 px-3 py-2.5">
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-text-primary" title={doc.fileName}>
            {doc.label}
          </span>
          <span className="block truncate text-xs text-text-secondary">{fileMeta(doc)}</span>
        </span>
        <a href={doc.snapshot?.url || documentFileUrl(workspaceId, doc.id)} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 text-xs text-primary hover:underline">
          <ExternalLink className="size-3" aria-hidden />
          원본
        </a>
      </div>

      <div ref={listRef} className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {range.start > 0 && (
          <button type="button" disabled={loading} onClick={() => void loadMore("prev")} className="mb-2 w-full cursor-pointer rounded-md border border-dashed border-neutral-300 py-1.5 text-xs text-text-secondary hover:border-primary hover:text-primary">
            앞 문단 더 보기 ({range.start})
          </button>
        )}
        {chunks.map((c, i) => {
          const showHeading = c.heading && c.heading !== chunks[i - 1]?.heading;
          const focused = focusChunk === c.id;
          return (
            <div key={c.id} data-chunk={c.id} className={cn("mb-2 rounded-lg px-2.5 py-2", focused ? "bg-yellow-100/80 ring-1 ring-yellow-300" : "hover:bg-neutral-50")}>
              {showHeading && <p className="mb-1 text-[11px] font-semibold text-primary">§ {c.heading}</p>}
              {FEATURES.assets && c.kind === "table" && (c.rows?.length ?? 0) > 1 && !/r\d+$/.test(c.id) && (
                <button
                  type="button"
                  disabled={making !== null}
                  onClick={() => void toAsset(c.id)}
                  className="mb-1 inline-flex cursor-pointer items-center gap-1 rounded-md bg-neutral-100 px-2 py-0.5 text-[11px] font-medium text-neutral-600 hover:bg-primary-soft hover:text-primary disabled:opacity-50"
                >
                  {making === c.id ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Table2 className="size-3" aria-hidden />}
                  에셋으로
                </button>
              )}
              <ChunkBody chunk={c} focusCell={focused ? focusCell : null} />
              {(c.page || c.sheet) && <p className="mt-0.5 text-[10px] text-text-secondary">{c.page ? `p.${c.page}` : `시트 ${c.sheet}`}</p>}
            </div>
          );
        })}
        <div ref={sentinelRef} className="h-6" />
        {loading && (
          <p className="flex items-center justify-center gap-1.5 py-2 text-xs text-text-secondary">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            불러오는 중
          </p>
        )}
        {error && <p className="py-2 text-center text-xs text-red-600">{error}</p>}
      </div>
    </div>
  );
});
