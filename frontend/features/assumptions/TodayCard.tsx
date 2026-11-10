"use client";

/** 홈 '오늘 확인할 것' — 판정이 바뀌고 아직 넘기지 않은 감시 가정 + 루틴이 쓴 문서. 가정을 누르면 가정 서랍(그 문서의 그 가정). */
import { useEffect, useState } from "react";
import { useAtomValue, useSetAtom } from "jotai";
import { FileText, Flag, ListChecks, Scale } from "lucide-react";

import { proposalsDrawerAtom } from "../criteria/state";
import { useWorkspace } from "../workspace/context";
import { getToday, type TodayPayload } from "./api";
import { assumptionsDrawerAtom, docAssumptionsAtom } from "./state";

const ago = (iso: string) => {
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  if (m < 60) return m < 1 ? "방금" : `${m}분 전`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h}시간 전` : `${Math.round(h / 24)}일 전`;
};

export function TodayCard() {
  const ws = useWorkspace();
  const open = useSetAtom(assumptionsDrawerAtom);
  const openProposals = useSetAtom(proposalsDrawerAtom);
  const drawer = useAtomValue(assumptionsDrawerAtom);
  const docState = useAtomValue(docAssumptionsAtom);
  const [data, setData] = useState<TodayPayload | null>(null);

  // 서랍을 닫을 때(넘기기·다시 판정 뒤) 다시 불러온다
  useEffect(() => {
    if (drawer) return;
    let cancelled = false;
    getToday(ws.workspaceId).then(
      (d) => !cancelled && setData(d),
      () => !cancelled && setData({ assumptions: [], watching: 0, routineDocs: [] }),
    );
    return () => {
      cancelled = true;
    };
  }, [ws.workspaceId, drawer, docState]);

  const changed = data?.assumptions ?? [];
  const routines = data?.routineDocs ?? [];
  const proposals = data?.proposals ?? [];
  const pending = data?.criteriaPending ?? 0;
  const total = changed.length + routines.length + proposals.length + (pending ? 1 : 0);
  // 검토 제안 — 문서를 열고 그 제안으로 서랍을 연다
  const openProposal = (p: { id: string; reportId: string; reportTitle: string }) => {
    ws.nav.openReport(p.reportId);
    setTimeout(() => openProposals({ reportId: p.reportId, title: p.reportTitle, focusId: p.id }), 0);
  };

  return (
    <section className="rounded-[24px] bg-white px-6 py-5">
      <h2 className="flex items-center gap-2 text-[19px] font-bold text-text-primary">
        오늘 확인할 것 {total > 0 && <span className="text-primary">{total}</span>}
      </h2>
      <div className="mt-3 flex flex-col">
        {data === null && <p className="py-4 text-[13px] text-text-secondary">불러오는 중…</p>}
        {data && !total && <p className="py-4 text-[13px] text-text-secondary">{data.watching ? `감시 중인 가정 ${data.watching}개 — 바뀐 판정이 없습니다.` : "확인할 것이 없습니다."}</p>}
        {proposals.map((p) => (
          <button key={p.id} type="button" onClick={() => openProposal(p)} className="flex cursor-pointer items-start gap-3 rounded-xl px-2 py-2.5 text-left hover:bg-neutral-50">
            <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-neutral-100 text-neutral-700">
              <Scale className="size-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14px] font-semibold text-text-primary">
                {p.directionKo} 검토 제안 · {p.reportTitle}
              </span>
              <span className="block truncate text-[12px] text-text-secondary">
                {p.changed}
                {p.criterion && ` · 기준 ${p.criterion}`}
              </span>
            </span>
          </button>
        ))}
        {pending > 0 && (
          <button type="button" onClick={() => ws.nav.view("criteria")} className="flex cursor-pointer items-start gap-3 rounded-xl px-2 py-2.5 text-left hover:bg-neutral-50">
            <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-neutral-100 text-neutral-700">
              <ListChecks className="size-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14px] font-semibold text-text-primary">판단 기준 승인 대기 {pending}</span>
              <span className="block truncate text-[12px] text-text-secondary">자료에서 뽑은 초안·승인된 문서에서 나온 수정안</span>
            </span>
          </button>
        )}
        {changed.map((a) => (
          <button key={a.id} type="button" onClick={() => open({ docKind: a.docKind, docRef: a.docRef, title: a.docTitle, focusId: a.id })} className="flex cursor-pointer items-start gap-3 rounded-xl px-2 py-2.5 text-left hover:bg-neutral-50">
            <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-neutral-100 text-neutral-700">
              <Flag className="size-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14px] font-semibold text-text-primary">
                {a.role === "trigger" && <span className="mr-1 font-normal text-text-secondary">재심의 조건</span>}“{a.quote}”
              </span>
              <span className="block truncate text-[12px] text-text-secondary">
                {a.conditionText} · 지금 {a.latest?.value.display || "—"} · <b className="font-semibold text-text-primary">{a.latest?.resultKo}</b>
                {a.latest?.changed && a.latest.prevKo && ` (이전 ${a.latest.prevKo})`} · {a.docTitle}
              </span>
            </span>
          </button>
        ))}
        {routines.slice(0, 4).map((r) => (
          <button key={r.id} type="button" onClick={() => ws.nav.openReport(r.id)} className="flex cursor-pointer items-start gap-3 rounded-xl px-2 py-2.5 text-left hover:bg-neutral-50">
            <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-primary-soft text-primary">
              <FileText className="size-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14px] font-semibold text-text-primary">{r.title}</span>
              <span className="block truncate text-[12px] text-text-secondary">
                루틴 {r.routine} · {ago(r.updatedAt)}
                {r.status === "draft" && " · AI 초안"}
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
