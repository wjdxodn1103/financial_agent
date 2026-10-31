"use client";

/** 대화로 등록 확인 카드 — AI 가 낸 루틴·수집 소스. [등록] 해야 저장된다(고쳐서 등록은 창으로). */
import { useState } from "react";
import { Check, Repeat, TrendingUp } from "lucide-react";
import { toast } from "sonner";
import { createSource } from "../data/api";
import { ApiError } from "../report/api";
import type { Proposal } from "../report/types";
import { useWorkspace } from "../workspace/context";
import { createRoutine } from "./api";
import { RoutineDialog } from "./RoutineDialog";
import { scheduleKo } from "./RoutinesView";

const SRC_KO = { edgar: "공시(SEC EDGAR)", series: "시장·거시 시계열", rss: "공식 보도자료·성명" } as const;

export function ProposalCard({ p }: { p: Exclude<Proposal, { kind: "event_alert" }> }) {
  const ws = useWorkspace();
  const [done, setDone] = useState(false);
  const [editing, setEditing] = useState(false);
  const sch = { every: p.schedule.every === "hourly" ? "daily" : p.schedule.every, time: p.schedule.times[0] ?? "07:00", weekday: p.schedule.weekday } as const;

  const register = async () => {
    try {
      if (p.kind === "routine") {
        if (!p.formatId) return setEditing(true);
        await createRoutine(ws.workspaceId, { name: p.name, formatId: p.formatId, instruction: p.instruction, schedule: sch, recipients: { all: p.notifyAll }, source: { kind: "chat", sessionId: p.sessionId } });
      } else {
        await createSource(ws.workspaceId, {
          kind: p.sourceKind,
          scope: "workspace",
          name: p.name || SRC_KO[p.sourceKind],
          params: p.sourceKind === "edgar" ? { companies: p.companies ?? [] } : p.sourceKind === "series" ? { seriesIds: p.seriesIds ?? [] } : { feeds: p.feeds ?? [] },
          schedule: { every: p.schedule.every, times: p.schedule.times },
        });
      }
      setDone(true);
      toast.success("등록했습니다.", { position: "top-center" });
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "등록하지 못했습니다.", { position: "top-center" });
    }
  };

  const Icon = p.kind === "routine" ? Repeat : TrendingUp;
  return (
    <div className="w-full max-w-[520px] rounded-2xl bg-neutral-50 px-4 py-3.5 ring-1 ring-neutral-200">
      <p className="flex items-center gap-2 text-[14px] font-semibold text-text-primary">
        <Icon className="size-4 text-primary" aria-hidden />
        {p.kind === "routine" ? "루틴 등록" : "수집 소스 등록"} — {p.name || (p.kind === "source" ? SRC_KO[p.sourceKind] : "")}
      </p>
      <dl className="mt-2 grid grid-cols-[72px_minmax(0,1fr)] gap-x-2 gap-y-1 text-[13px]">
        {p.kind === "routine" ? (
          <>
            <dt className="text-text-secondary">양식</dt>
            <dd className="text-text-primary">{p.formatTitle || <span className="text-amber-700">고르기 필요</span>}</dd>
            <dt className="text-text-secondary">언제</dt>
            <dd className="text-text-primary">{scheduleKo(sch)}</dd>
            <dt className="text-text-secondary">알림</dt>
            <dd className="text-text-primary">{p.notifyAll ? "워크스페이스 전원" : "나"}</dd>
            {p.folderName && (
              <>
                <dt className="text-text-secondary">폴더</dt>
                <dd className="text-text-primary">{p.folderName}</dd>
              </>
            )}
            <dt className="text-text-secondary">지시</dt>
            <dd className="line-clamp-3 text-text-primary">{p.instruction}</dd>
          </>
        ) : (
          <>
            <dt className="text-text-secondary">종류</dt>
            <dd className="text-text-primary">{SRC_KO[p.sourceKind]}</dd>
            {p.companies && (
              <>
                <dt className="text-text-secondary">회사</dt>
                <dd className="text-text-primary">
                  {p.companies.map((c) => c.name).join(", ") || "—"}
                  {p.missing?.length ? <span className="text-amber-700"> · 못 찾음: {p.missing.join(", ")}</span> : null}
                </dd>
              </>
            )}
            {p.seriesIds && (
              <>
                <dt className="text-text-secondary">시리즈</dt>
                <dd className="text-text-primary">{p.seriesIds.length}개</dd>
              </>
            )}
            <dt className="text-text-secondary">언제</dt>
            <dd className="text-text-primary">{p.schedule.every === "hourly" ? "매시간" : scheduleKo(sch)}</dd>
          </>
        )}
      </dl>
      <div className="mt-3 flex gap-2">
        {done ? (
          <span className="flex items-center gap-1 text-[13px] font-semibold text-primary">
            <Check className="size-4" aria-hidden />
            등록했습니다
          </span>
        ) : (
          <>
            <button type="button" onClick={() => void register()} className="h-8 cursor-pointer rounded-lg bg-primary px-3 text-[12px] font-semibold text-white hover:bg-primary-hover">
              등록
            </button>
            {p.kind === "routine" && (
              <button type="button" onClick={() => setEditing(true)} className="h-8 cursor-pointer rounded-lg bg-white px-3 text-[12px] font-semibold text-neutral-700 ring-1 ring-neutral-200 hover:bg-neutral-50">
                고쳐서 등록
              </button>
            )}
          </>
        )}
      </div>
      {editing && p.kind === "routine" && (
        <RoutineDialog
          initial={{ name: p.name, formatId: p.formatId ?? "", instruction: p.instruction, schedule: sch, recipients: { all: p.notifyAll }, folderName: p.folderName, source: { kind: "chat", sessionId: p.sessionId } }}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            setDone(true);
          }}
        />
      )}
    </div>
  );
}
