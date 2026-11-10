"use client";

/**
 * 대시보드 화면 — 전사 '시장'·'데이터 현황'(전원 보기, 관리자 고치기)과 '우리 워크스페이스'(편집자 이상 고치기).
 * 고치기 = 위 가운데 대화창에 말하기 → AI 가 구성을 제안(바로 바꾸지 않음) → '지금 | 제안' 미리보기 → 제안한 사람이 [승인]·[버리기].
 */
import { useCallback, useEffect, useState, type KeyboardEvent } from "react";
import { Loader2, RefreshCw, Send, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { refreshMarket } from "../data/api";
import { ApiError } from "../report/api";
import { useWorkspace } from "../workspace/context";
import { decideDraft, getDashboard, proposeDashboard } from "./api";
import { MarketHome } from "./MarketHome";
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
  // 대화창에는 지금 보이는 구성을 만든 요청이 남는다(다시 말하면 그 자리에서 고쳐 쓴다)
  const shown = view?.prompt ?? "";
  useEffect(() => {
    setText(shown);
  }, [shown]);

  const propose = async () => {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    try {
      const v = await proposeDashboard(kind, ws.workspaceId, t);
      setView(v);
      setPreview(true);
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
        <div className="mx-auto grid max-w-[1280px] grid-cols-[1fr_minmax(0,720px)_1fr] items-center gap-4 px-8 pt-7 pb-2">
          <h1 className="text-[24px] leading-tight font-bold tracking-tight text-text-primary">{title}</h1>
          {view?.canEdit ? (
            <div className="flex items-end gap-2 rounded-[20px] bg-white px-4 py-2.5 ring-1 ring-primary/50">
              <Sparkles className="mb-1 size-5 shrink-0 text-primary" aria-hidden />
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={onKey}
                onFocus={(e) => e.currentTarget.select()}
                rows={1}
                placeholder="무엇을 볼지 말해 주세요 — 예: 삼성전자와 SK하이닉스의 산업 전망과 실적을 비교해줘"
                className="max-h-28 min-h-6 flex-1 resize-none bg-transparent text-[14px] leading-7 font-medium outline-none placeholder:font-normal placeholder:text-neutral-400"
              />
              <button type="button" aria-label="보내기" disabled={busy || !text.trim()} onClick={() => void propose()} className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full bg-primary text-white disabled:opacity-40">
                {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
              </button>
            </div>
          ) : (
            <span />
          )}
          <div className="flex items-center justify-end gap-2">
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
        <div className="mx-auto max-w-[1280px] px-8 pb-3 text-center text-[12px] text-text-secondary">
          {busy ? (
            "자료를 모으고 구성을 만드는 중입니다…"
          ) : view?.template ? (
            <>
              양식 <b className="font-semibold text-text-primary">{view.template.label}</b> 적용
            </>
          ) : kind === "market" ? (
            "전사 공유 · 주요 지수·환율·원자재·금리를 한 화면에 — 카드나 줄을 누르면 위 차트가 바뀝니다"
          ) : kind === "data" ? (
            "전사 공유 · 출처: 미 재무부·ECB·뉴욕 연은(실데이터), FRED(키 있을 때), 데모(가상)"
          ) : null}
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
        {kind === "market" && <MarketHome />}
        {kind === "market" && (
          <div className="mx-auto max-w-[1280px] px-8 pt-4 pb-2">
            <h2 className="text-[13px] font-semibold text-text-secondary">시장 위젯 · AI 요약</h2>
          </div>
        )}
        <div className="mx-auto grid max-w-[1280px] grid-cols-1 gap-3 px-8 pb-10 lg:grid-cols-12">
          {!view && <Loader2 className="col-span-12 mx-auto my-20 size-6 animate-spin text-neutral-400" />}
          {view?.widgets.map((w) =>
            w.type === "peer_board" ? (
              // 양식 위젯은 안에서 카드를 나눠 그린다(겉 카드 없이 화면 폭 전체)
              <div key={w.id} className="min-w-0 lg:col-span-12">
                <WidgetBody w={w} onSeries={setSeries} />
              </div>
            ) : (
              <section key={w.id} className={cn("min-w-0 rounded-[24px] bg-white px-5 py-4", SIZE_CLASS[w.size])}>
                <h2 className="mb-3 text-[15px] font-bold text-text-primary">{w.title}</h2>
                <WidgetBody w={w} onSeries={setSeries} />
              </section>
            ),
          )}
        </div>
      </div>
      {series && <SeriesModal id={series} onClose={() => setSeries(null)} />}
    </div>
  );
}
