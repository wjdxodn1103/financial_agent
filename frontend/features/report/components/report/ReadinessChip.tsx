"use client";

/**
 * 검토 준비 칩 — 리포트 상단. BE 코드 점검표(미작성·미해결 충돌·채택값과 다름·원장과 다른 숫자·근거 없는 숫자·잘린 본문).
 * 누르면 항목 목록(누르면 그 섹션으로) + 작성자는 "검토 요청"(검토자 작업 항목 + 채널 알림). 확인할 것이 남아 있어도 막지 않는다.
 */
import { useEffect, useRef, useState } from "react";
import { useAtomValue } from "jotai";
import { AlertTriangle, CheckCircle2, ChevronDown, Loader2, PencilLine, Send } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { useWorkspace } from "../../../workspace/context";
import { FEATURES } from "../../../workspace/features";
import { readinessAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import type { Readiness } from "../../types";

const TASK_KO: Record<string, string> = { todo: "할 일", doing: "진행", review: "검토", done: "완료" };

function label(r: Readiness): { text: string; tone: string; icon: typeof AlertTriangle } {
  if (r.state === "ready") return { text: "검토 준비됨", tone: "border-emerald-200 bg-emerald-50 text-emerald-800", icon: CheckCircle2 };
  if (r.state === "attention") return { text: `확인 필요 ${r.issues}`, tone: "border-amber-200 bg-amber-50 text-amber-800", icon: AlertTriangle };
  if (r.state === "writing") return { text: `작성 중 ${r.written}/${r.sections}${r.issues ? ` · 확인 ${r.issues}` : ""}`, tone: "border-neutral-200 bg-white text-text-secondary", icon: PencilLine };
  return { text: "아직 쓴 섹션 없음", tone: "border-neutral-200 bg-white text-text-secondary", icon: PencilLine };
}

function when(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function ReadinessChip() {
  const r = useAtomValue(readinessAtom);
  const ws = useWorkspace();
  const actions = useReportActions();
  const [open, setOpen] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  if (!r) return null;
  const { text, tone, icon: Icon } = label(r);
  const reviewers = (ws.detail?.members ?? []).filter((m) => m.user.id !== ws.me.id && m.role !== "viewer");
  const unwritten = r.items.filter((i) => i.kind === "unwritten");
  const issues = r.items.filter((i) => i.kind !== "unwritten");
  const req = r.reviewRequest;

  const send = async () => {
    if (!reviewer || sending) return;
    setSending(true);
    if (await actions.requestReview(reviewer, note)) {
      toast.success(`${ws.nameOf(reviewer)}님께 검토를 요청했습니다. 작업 항목과 채널에 남겼습니다.`, { position: "top-center" });
      setNote("");
    }
    setSending(false);
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={cn("flex h-7 cursor-pointer items-center gap-1 rounded-full border px-2.5 text-[11px] font-medium", tone)}
      >
        <Icon className="size-3.5" aria-hidden />
        {text}
        <ChevronDown className="size-3" aria-hidden />
      </button>
      {open && (
        <div className="absolute top-full right-0 z-30 mt-1 w-[380px] rounded-xl border border-neutral-200 bg-white p-3 text-xs shadow-lg">
          <p className="font-semibold text-text-primary">검토 준비 점검</p>
          <p className="mt-0.5 text-[11px] text-text-secondary">코드가 지금 본문과 지금 원장으로 다시 잰 결과입니다(AI 판단 아님).</p>
          <div className="thin-scrollbar mt-2 flex max-h-[260px] flex-col gap-1 overflow-y-auto">
            {issues.length === 0 && unwritten.length === 0 && <p className="text-emerald-700">확인할 것이 없습니다.</p>}
            {issues.map((i, n) => (
              <button
                key={n}
                type="button"
                onClick={() => {
                  if (i.key) actions.openNumber(i.key);
                  else actions.openSection(i.step);
                  setOpen(false);
                }}
                className="flex cursor-pointer items-start gap-1.5 rounded-md px-1.5 py-1 text-left hover:bg-neutral-50"
              >
                <span className={cn("shrink-0 rounded px-1 py-0.5 text-[10px]", i.kind === "conflict" || i.kind === "mismatch" || i.kind === "wrongcite" ? "bg-amber-100 text-amber-800" : "bg-neutral-100 text-text-secondary")}>
                  {r.kindKo[i.kind]}
                </span>
                <span className="min-w-0 text-text-primary">
                  <span className="text-text-secondary">{i.title} · </span>
                  {i.text}
                </span>
              </button>
            ))}
            {unwritten.length > 0 && (
              <p className="px-1.5 py-1 text-text-secondary">
                <span className="mr-1 rounded bg-neutral-100 px-1 py-0.5 text-[10px]">미작성 {unwritten.length}</span>
                {unwritten.map((u) => u.title).join(", ")}
              </p>
            )}
          </div>

          {FEATURES.reviewRequest && (
            <div className="mt-3 border-t border-neutral-100 pt-2.5">
              {req && (
                <p className="mb-2 rounded-md bg-background-gray px-2 py-1.5 text-[11px] text-text-secondary">
                  {ws.nameOf(req.reviewerId)}님께 검토 요청 · {when(req.requestedAt)} · 작업 {req.taskStatus ? TASK_KO[req.taskStatus] : "없음"}
                  <br />
                  요청 때: {req.summary}
                </p>
              )}
              {r.canRequest ? (
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center gap-1.5">
                    <select
                      aria-label="검토자"
                      value={reviewer}
                      onChange={(e) => setReviewer(e.target.value)}
                      className="min-w-0 flex-1 rounded-md border border-neutral-200 bg-white px-2 py-1 text-xs"
                    >
                      <option value="">검토자 고르기</option>
                      {reviewers.map((m) => (
                        <option key={m.user.id} value={m.user.id}>
                          {m.user.name} {m.user.title}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      disabled={!reviewer || sending}
                      onClick={() => void send()}
                      className="inline-flex cursor-pointer items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs text-white hover:bg-primary-hover disabled:opacity-50"
                    >
                      {sending ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Send className="size-3" aria-hidden />}
                      {req ? "다시 요청" : "검토 요청"}
                    </button>
                  </div>
                  <input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="요청 메모(선택) — 예: 매출 충돌은 IR 자료 기준으로 봤습니다"
                    className="rounded-md border border-neutral-200 px-2 py-1 text-xs"
                  />
                  {r.issues > 0 && <p className="text-[11px] text-amber-700">확인할 것 {r.issues}건이 남아 있습니다 — 요청은 되고, 남은 항목이 작업 항목에 함께 적힙니다.</p>}
                </div>
              ) : (
                !req && <p className="text-[11px] text-text-secondary">검토 요청은 리포트 작성자가 합니다.</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
