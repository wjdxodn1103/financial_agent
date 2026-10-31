"use client";

/**
 * 문서 검수 ▸ 가이드라인 점검 — 사내 투자정책서의 한도(문장 원문)와 포트폴리오 보유 내역(칸 원문)을 나란히.
 * 조건은 정책서 문장에서 뽑고(인용 대조), 값은 보유 표에서 코드가 더한다. 판정은 한 낱말(지킴·넘음·목표·계산 못 함), 색 없음.
 */
import { useEffect, useState } from "react";
import { Loader2, Play } from "lucide-react";
import { toast } from "sonner";

import { ApiError } from "../report/api";
import { useWorkspace } from "../workspace/context";
import { PageHeader } from "../workspace/components/views/PageHeader";
import { useOpenSource } from "../workspace/sourceHost";
import type { AnchorRef } from "../assumptions/api";
import { getGuideline, runGuideline, type GuidelineResult } from "./api";

const when = (iso: string) => new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

export function GuidelineView() {
  const ws = useWorkspace();
  const openSource = useOpenSource();
  const [res, setRes] = useState<GuidelineResult | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getGuideline(ws.workspaceId).then(setRes, () => setRes(null));
  }, [ws.workspaceId]);

  const run = async () => {
    setBusy(true);
    try {
      setRes(await runGuideline(ws.workspaceId));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "점검하지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };
  const open = (a?: AnchorRef | null) => a?.docId && openSource(a.docId, a.chunk ?? null, a.cell ?? null);

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
      <PageHeader
        title="가이드라인 점검"
        wide
        desc={res ? `${res.policy.title} × ${res.portfolio.title} · ${when(res.checkedAt)}` : undefined}
        actions={
          <button type="button" disabled={busy} onClick={() => void run()} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />}
            {busy ? "점검 중…" : "점검"}
          </button>
        }
      />
      <div className="mx-auto max-w-[1180px] px-8 pb-14">
        {res === undefined && <p className="text-[13px] text-text-secondary">불러오는 중…</p>}
        {res === null && <p className="rounded-[20px] bg-white px-6 py-8 text-[14px] text-text-secondary">[점검]을 누르면 사내 투자정책서의 한도를 포트폴리오 보유 내역과 대조합니다.</p>}
        {res && (
          <div className="overflow-hidden rounded-[20px] bg-white">
            <div className="grid grid-cols-[88px_minmax(0,1.6fr)_120px_96px_minmax(0,1fr)] gap-3 border-b border-neutral-200 px-5 py-2.5 text-[12px] font-semibold text-neutral-500">
              <span>판정</span>
              <span>정책서 문장</span>
              <span>한도</span>
              <span>지금</span>
              <span>계산</span>
            </div>
            {res.items.map((it, i) => (
              <div key={i} className="grid grid-cols-[88px_minmax(0,1.6fr)_120px_96px_minmax(0,1fr)] items-start gap-3 border-b border-neutral-100 px-5 py-3 text-[13px] last:border-0">
                <b className="font-semibold text-text-primary">{it.resultKo}</b>
                <button type="button" onClick={() => open(it.policyAnchor)} title="정책서 원문" className="cursor-pointer text-left leading-5 text-text-primary hover:text-primary">
                  “{it.quote}”
                </button>
                <span className="tabular-nums">
                  {it.label === "기타" ? "" : `${it.label} `}
                  {it.limit}
                </span>
                <span className="tabular-nums">
                  {it.valueDisplay}
                  {it.gap != null && it.result !== "na" && <span className="block text-[11px] text-text-secondary">{`${it.gap > 0 ? "▲" : it.gap < 0 ? "▼" : ""}${Math.abs(it.gap)}%p`}</span>}
                </span>
                <span className="min-w-0 text-[12px] text-text-secondary">
                  {it.how}
                  {it.anchors.length > 0 && (
                    <span className="mt-1 flex flex-wrap gap-1">
                      {it.anchors.slice(0, 6).map((a, j) => (
                        <button key={j} type="button" onClick={() => open(a)} title={a.quote} className="h-6 cursor-pointer rounded-md border border-neutral-200 px-1.5 text-[11px] text-text-primary hover:bg-neutral-50">
                          {a.rowLabel || `칸 ${j + 1}`}
                        </button>
                      ))}
                      {it.anchors.length > 6 && <span className="self-center text-[11px]">외 {it.anchors.length - 6}</span>}
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
