"use client";

/**
 * 자료 속 표 — 표마다 [에셋으로](칸 = 원문 칸, LLM 없음). 이미 이 자료로 만든 에셋은 [열기],
 * 비슷한 문서에서 만든 같은 모양 표가 있으면 [같은 모양으로 만들기](그 에셋의 열·단위·이름 그대로, 그 표로 만든 차트도).
 * 비교 대상은 내 에셋 + 공유된 에셋만.
 */
import { useCallback, useEffect, useState } from "react";
import { Check, Copy, Loader2, Table2, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError } from "../../report/api";
import type { DocumentCard } from "../../report/types";
import { applySimilar, docTableAsset, docTables, similarAssets, type DocTable, type SimilarAssets } from "../../research/api";
import { useWorkspace } from "../context";

export function DocTablesDialog({ doc, onClose, onChanged }: { doc: DocumentCard; onClose: () => void; onChanged?: () => void }) {
  const ws = useWorkspace();
  const [tables, setTables] = useState<DocTable[] | null>(null);
  const [sim, setSim] = useState<SimilarAssets | null>(null);
  const [made, setMade] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [t, s] = await Promise.all([docTables(ws.workspaceId, doc.id), similarAssets(ws.workspaceId, doc.id)]);
      setTables(t.tables);
      setSim(s);
    } catch {
      setTables([]);
    }
  }, [doc.id, ws.workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (key: string, fn: () => Promise<void>, fail: string) => {
    setBusy(key);
    try {
      await fn();
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : fail, { position: "top-center" });
    } finally {
      setBusy(null);
    }
  };

  const similarOf = (chunk: string) => sim?.similar.find((s) => s.chunk === chunk);
  const pending = (sim?.similar ?? []).filter((s) => !made[s.chunk]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="thin-scrollbar flex max-h-[86vh] w-full max-w-[640px] flex-col overflow-y-auto rounded-[24px] bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[20px] font-bold tracking-tight text-text-primary">자료 속 표</h2>
            <p className="mt-0.5 truncate text-[13px] text-text-secondary">{doc.label}</p>
          </div>
          <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>

        {pending.length > 1 && (
          <div className="mt-4 flex items-center gap-3 rounded-2xl bg-primary-soft px-4 py-3">
            <Copy className="size-4 shrink-0 text-primary" aria-hidden />
            <p className="min-w-0 flex-1 text-[13px] text-primary-soft-foreground">비슷한 문서에서 만든 같은 모양 표 {pending.length}개</p>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() =>
                void run(
                  "all",
                  async () => {
                    const r = await applySimilar(ws.workspaceId, doc.id, pending.map((s) => ({ chunk: s.chunk, assetId: s.asset.id })));
                    setMade((m) => ({ ...m, ...Object.fromEntries(pending.map((s) => [s.chunk, "done"])) }));
                    toast.success(`에셋 ${r.tables.length}개를 만들었습니다.`, { position: "top-center" });
                  },
                  "만들지 못했습니다.",
                )
              }
              className="h-8 shrink-0 cursor-pointer rounded-lg bg-primary px-3 text-[12px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
            >
              모두 같은 모양으로
            </button>
          </div>
        )}

        <div className="mt-4 flex flex-col gap-1.5">
          {tables === null && <p className="py-6 text-center text-[14px] text-neutral-500">불러오는 중…</p>}
          {tables?.length === 0 && <p className="py-6 text-center text-[14px] text-neutral-500">칸 구조 표가 없는 자료입니다.</p>}
          {tables?.map((t) => {
            const s = similarOf(t.chunk);
            const done = made[t.chunk] || sim?.same.some((a) => a.chunk === t.chunk);
            return (
              <div key={t.chunk} className="flex items-center gap-3 rounded-xl bg-neutral-50 px-3 py-2.5">
                <Table2 className="size-4 shrink-0 text-primary" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-medium text-text-primary">{t.caption || `표 ${t.no}`}</span>
                  <span className="block truncate text-[12px] text-text-secondary">
                    {[t.page ? `p.${t.page}` : null, `${t.rows}행 × ${t.cols}열`, s && !done ? `같은 모양: ${s.asset.title}${s.asset.mine ? "" : ` (${s.asset.createdBy})`}` : null].filter(Boolean).join(" · ")}
                  </span>
                </span>
                {done ? (
                  <span className="flex shrink-0 items-center gap-1 text-[12px] font-semibold text-primary">
                    <Check className="size-3.5" aria-hidden />
                    에셋
                  </span>
                ) : (
                  <span className="flex shrink-0 gap-1">
                    {s && (
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() =>
                          void run(
                            t.chunk,
                            async () => {
                              await applySimilar(ws.workspaceId, doc.id, [{ chunk: t.chunk, assetId: s.asset.id }]);
                              setMade((m) => ({ ...m, [t.chunk]: "done" }));
                            },
                            "만들지 못했습니다.",
                          )
                        }
                        className="h-8 cursor-pointer rounded-lg bg-primary px-2.5 text-[12px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
                      >
                        같은 모양으로
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() =>
                        void run(
                          t.chunk,
                          async () => {
                            await docTableAsset(ws.workspaceId, doc.id, t.chunk);
                            setMade((m) => ({ ...m, [t.chunk]: "done" }));
                          },
                          "꺼내지 못했습니다.",
                        )
                      }
                      className={cn("flex h-8 cursor-pointer items-center gap-1 rounded-lg px-2.5 text-[12px] font-semibold disabled:opacity-50", s ? "bg-neutral-200 text-neutral-700 hover:bg-neutral-300" : "bg-primary text-white hover:bg-primary-hover")}
                    >
                      {busy === t.chunk && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
                      에셋으로
                    </button>
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {(sim?.same.length ?? 0) > 0 && (
          <div className="mt-5">
            <p className="text-[13px] font-semibold text-neutral-600">이 자료로 이미 만든 에셋</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {sim!.same.map((a) => (
                <button key={a.id} type="button" onClick={() => (onClose(), ws.nav.openAsset(a.id))} className="max-w-[260px] cursor-pointer truncate rounded-full bg-neutral-100 px-3 py-1 text-[12px] font-medium text-neutral-700 hover:bg-neutral-200">
                  {a.title}
                  {!a.mine && <span className="text-neutral-500"> · {a.createdBy}</span>}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
