"use client";

/**
 * 대시보드 화면 — 전사 '시장'·'데이터 현황'(전원 보기, 관리자 고치기)과 '우리 워크스페이스'(편집자 이상 고치기).
 * 고치기 = 아래 입력줄에 말하기 → AI 가 구성을 제안(바로 바꾸지 않음) → '지금 | 제안' 미리보기 → 제안한 사람이 [승인]·[버리기].
 */
import { useCallback, useEffect, useState, type KeyboardEvent } from "react";
import { Loader2, RefreshCw, Send, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { refreshMarket } from "../data/api";
import { ApiError } from "../report/api";
import { useWorkspace } from "../workspace/context";
import { decideDraft, getDashboard, proposeDashboard } from "./api";
import type { DashboardKind, DashboardView } from "./types";
import { SeriesModal, SIZE_CLASS, WidgetBody } from "./widgets";

const err = (e: unknown, f: string) => (e instanceof ApiError && e.status < 500 ? e.message : f);

export function DashboardPage({ kind, title }: { kind: DashboardKind; title: string }) {
  const ws = useWorkspace();
  const [view, setView] = useState<DashboardView | null>(null);
  const [preview, setPreview] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [series, setSeries] = useState<string | null>(null);

  const load = useCallback(
    async (pv: boolean) => {
      try {
        setView(await getDashboard(kind, ws.workspaceId, pv));
      } catch (e) {
        toast.error(err(e, "대시보드를 불러오지 못했습니다."), { position: "top-center" });
      }
    },
    [kind, ws.workspaceId],
  );
  useEffect(() => {
    void load(preview);
  }, [load, preview]);

  const propose = async () => {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    try {
      const v = await proposeDashboard(kind, ws.workspaceId, t);
      setView(v);
      setPreview(true);
      setText("");
    } catch (e) {
      toast.error(err(e, "제안을 만들지 못했습니다."), { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };
  const decide = async (approve: boolean) => {
    if (!view?.draft) return;
    try {
      const v = await decideDraft(view.draft.id, approve);
      setPreview(false);
      setView(v);
      toast.success(approve ? "새 구성을 적용했습니다." : "제안을 버렸습니다.", { position: "top-center" });
    } catch (e) {
      toast.error(err(e, "처리하지 못했습니다."), { position: "top-center" });
    }
  };
  const refresh = async () => {
    try {
      await refreshMarket();
      toast.success("시장 데이터를 다시 받고 있습니다. 잠시 뒤 새로 고쳐집니다.", { position: "top-center" });
      window.setTimeout(() => void load(preview), 15000);
    } catch (e) {
      toast.error(err(e, "갱신하지 못했습니다."), { position: "top-center" });
    }
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void propose();
    }
  };

  const d = view?.draft;
  return (
    <div className="relative flex min-h-0 flex-1 flex-col bg-neutral-100">
      <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-[1280px] items-end justify-between gap-4 px-8 pt-8 pb-4">
          <div>
            <h1 className="text-[26px] leading-tight font-bold tracking-tight text-text-primary">{title}</h1>
            {kind !== "workspace" && <p className="mt-1 text-[13px] text-text-secondary">전사 공유 · 출처: 미 재무부·ECB·뉴욕 연은(실데이터), FRED(키 있을 때), 데모(가상)</p>}
          </div>
          <div className="flex items-center gap-2">
            {d && d.mine && (
              <div className="flex items-center rounded-xl bg-white p-1 text-[13px] font-semibold">
                <button type="button" onClick={() => setPreview(false)} className={cn("cursor-pointer rounded-lg px-3 py-1.5", !preview ? "bg-neutral-100 text-text-primary" : "text-text-secondary")}>
                  지금
                </button>
                <button type="button" onClick={() => setPreview(true)} className={cn("cursor-pointer rounded-lg px-3 py-1.5", preview ? "bg-primary-soft text-primary" : "text-text-secondary")}>
                  제안
                </button>
              </div>
            )}
            {d && !d.mine && <span className="rounded-lg bg-white px-3 py-1.5 text-[12px] text-text-secondary">{d.by}님의 변경 제안 대기</span>}
            {kind === "data" && view?.canEdit && (
              <button type="button" onClick={() => void refresh()} className="flex h-9 cursor-pointer items-center gap-1.5 rounded-xl bg-white px-3 text-[13px] font-semibold text-neutral-700 hover:bg-neutral-50">
                <RefreshCw className="size-4" aria-hidden />
                시장 지금 갱신
              </button>
            )}
          </div>
        </div>
        {d && d.mine && preview && (
          <div className="mx-auto mb-3 flex max-w-[1280px] items-center gap-3 px-8">
            <div className="flex flex-1 items-center gap-2 rounded-2xl bg-primary-soft px-4 py-2.5 text-[13px] text-primary">
              <Sparkles className="size-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{d.summary || "AI 가 낸 구성"}</span>
            </div>
            <button type="button" onClick={() => void decide(false)} className="h-10 cursor-pointer rounded-xl bg-white px-4 text-[13px] font-semibold text-neutral-700 hover:bg-neutral-50">
              버리기
            </button>
            <button type="button" onClick={() => void decide(true)} className="h-10 cursor-pointer rounded-xl bg-primary px-4 text-[13px] font-semibold text-white hover:bg-primary-hover">
              승인
            </button>
          </div>
        )}
        <div className="mx-auto grid max-w-[1280px] grid-cols-1 gap-3 px-8 pb-28 lg:grid-cols-12">
          {!view && <Loader2 className="col-span-12 mx-auto my-20 size-6 animate-spin text-neutral-400" />}
          {view?.widgets.map((w) => (
            <section key={w.id} className={cn("min-w-0 rounded-[24px] bg-white px-5 py-4", SIZE_CLASS[w.size])}>
              <h2 className="mb-3 text-[15px] font-bold text-text-primary">{w.title}</h2>
              <WidgetBody w={w} onSeries={setSeries} />
            </section>
          ))}
        </div>
      </div>
      {view?.canEdit && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center px-8 pb-5">
          <div className="pointer-events-auto flex w-full max-w-[760px] items-end gap-2 rounded-[20px] bg-white px-4 py-3 shadow-[0_8px_30px_rgba(0,27,55,0.14)]">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={onKey}
              rows={1}
              placeholder="대시보드를 어떻게 바꿀지 말해 주세요 — 예: 원/달러 1년 차트 추가하고 할 일은 빼 줘"
              className="max-h-28 min-h-6 flex-1 resize-none bg-transparent text-[14px] leading-6 outline-none placeholder:text-neutral-400"
            />
            <button type="button" aria-label="보내기" disabled={busy || !text.trim()} onClick={() => void propose()} className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-xl bg-primary text-white disabled:opacity-40">
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
            </button>
          </div>
        </div>
      )}
      {series && <SeriesModal id={series} onClose={() => setSeries(null)} />}
    </div>
  );
}
