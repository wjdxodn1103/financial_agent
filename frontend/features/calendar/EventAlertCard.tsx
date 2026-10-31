"use client";

/** 대화로 일정 알림 등록 — AI 가 찾은 일정(또는 지표의 다음 발표마다)을 보이고 [등록]해야 저장된다. 알림 메시지는 서버 코드 양식(AI 없음). */
import { useState } from "react";
import { BellRing, Check } from "lucide-react";
import { toast } from "sonner";

import { ApiError } from "../report/api";
import type { Proposal } from "../report/types";
import { useWorkspace } from "../workspace/context";
import { createEventAlerts } from "./api";

type EventAlertProposal = Extract<Proposal, { kind: "event_alert" }>;

export function EventAlertCard({ p }: { p: EventAlertProposal }) {
  const ws = useWorkspace();
  const [picked, setPicked] = useState(() => new Set(p.items.map((_, i) => i)));
  const [toAll, setToAll] = useState(p.notifyAll && ws.can("editor"));
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const register = async () => {
    const items = p.items.filter((_, i) => picked.has(i));
    setBusy(true);
    try {
      await createEventAlerts(ws.workspaceId, {
        eventIds: p.repeat ? items.filter((x) => !x.indicatorId && x.eventId).map((x) => x.eventId!) : items.map((x) => x.eventId).filter((x): x is string => !!x),
        indicatorIds: p.repeat ? items.map((x) => x.indicatorId).filter((x): x is string => !!x) : [],
        repeat: p.repeat,
        all: toAll,
        workspace: p.workspace,
        source: { kind: "chat" },
      });
      setDone(true);
      toast.success("알림을 등록했습니다.", { position: "top-center" });
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "등록하지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="w-full max-w-[520px] rounded-2xl bg-neutral-50 px-4 py-3.5 ring-1 ring-neutral-200">
      <p className="flex items-center gap-2 text-[14px] font-semibold text-text-primary">
        <BellRing className="size-4 text-primary" aria-hidden />
        일정 알림 등록{p.repeat ? " — 다음 발표마다" : ""}
      </p>
      <div className="mt-2 flex flex-col">
        {p.items.map((x, i) => (
          <label key={i} className="flex cursor-pointer items-start gap-2 py-1 text-[13px]">
            <input type="checkbox" disabled={done} checked={picked.has(i)} onChange={(e) => setPicked((s) => (e.target.checked ? new Set(s).add(i) : new Set([...s].filter((v) => v !== i))))} className="mt-0.5 size-4 accent-primary" />
            <span className="min-w-0 flex-1">
              <span className="block text-text-primary">{x.event ? x.event.title : x.name}</span>
              <span className="block text-[12px] text-text-secondary">
                {x.event ? [`${x.event.date} ${x.event.kstTime}`.trim(), x.event.localTime, x.event.period].filter(Boolean).join(" · ") : "다음 발표마다"}
              </span>
            </span>
          </label>
        ))}
        {p.missing.length > 0 && <p className="mt-1 text-[12px] text-text-secondary">찾지 못함: {p.missing.join(", ")}</p>}
      </div>
      <label className="mt-2 flex items-center gap-2 text-[13px]">
        <input type="checkbox" disabled={done || !ws.can("editor")} checked={toAll} onChange={(e) => setToAll(e.target.checked)} className="size-4 accent-primary" />
        워크스페이스 전원에게{p.workspace ? " · 워크스페이스 메시지로도" : ""}
      </label>
      <div className="mt-3 flex justify-end">
        {done ? (
          <span className="flex items-center gap-1 text-[13px] text-text-secondary">
            <Check className="size-4" aria-hidden />
            등록함
          </span>
        ) : (
          <button type="button" disabled={busy || picked.size === 0} onClick={() => void register()} className="h-9 cursor-pointer rounded-lg bg-primary px-4 text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
            등록
          </button>
        )}
      </div>
    </div>
  );
}
