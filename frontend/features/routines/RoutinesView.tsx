"use client";

/** AI 작업 ▸ 루틴 — 반복 작성 업무. 정한 시각에 만든 사람 이름으로 'AI 초안'을 써서 폴더에 올리고 알린다. [지금 실행]·[날짜 지정 실행](그날까지의 자료만). */
import { useCallback, useEffect, useState } from "react";
import { CalendarClock, FileText, Loader2, Pencil, Play, Plus, Repeat, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ApiError } from "../report/api";
import { useWorkspace } from "../workspace/context";
import { PageHeader } from "../workspace/components/views/PageHeader";
import { deleteRoutine, listRoutines, runRoutine, type Routine } from "./api";
import { RoutineDialog } from "./RoutineDialog";

const WEEK = ["월", "화", "수", "목", "금", "토", "일"];
const STATUS_KO: Record<string, string> = { ok: "완료", partial: "일부만", error: "실패", running: "쓰는 중" };

export function scheduleKo(s: Routine["schedule"]): string {
  if (s.every === "manual") return "손으로만";
  if (s.every === "weekdays") return `평일 ${s.time}`;
  if (s.every === "weekly") return `매주 ${WEEK[s.weekday ?? 0]} ${s.time}`;
  return `매일 ${s.time}`;
}

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function RoutinesView({ initial }: { initial: string | null }) {
  const ws = useWorkspace();
  const [rows, setRows] = useState<Routine[] | null>(null);
  const [editing, setEditing] = useState<Routine | null>(null);
  const [creating, setCreating] = useState(false);
  const [asOf, setAsOf] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      setRows(await listRoutines(ws.workspaceId));
    } catch {
      setRows([]);
    }
  }, [ws.workspaceId]);
  useEffect(() => {
    void load();
  }, [load]);
  const running = rows?.some((r) => r.lastRun?.status === "running");
  useEffect(() => {
    if (!running) return;
    const t = window.setTimeout(() => void load(), 4000);
    return () => window.clearTimeout(t);
  }, [running, rows, load]);

  const run = async (r: Routine, day?: string) => {
    try {
      await runRoutine(r.id, day);
      toast.success(day ? `${day} 기준으로 쓰기 시작했습니다. 끝나면 알림이 옵니다.` : "쓰기 시작했습니다. 끝나면 알림이 옵니다.", { position: "top-center" });
      window.setTimeout(() => void load(), 800);
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "실행하지 못했습니다.", { position: "top-center" });
    }
  };
  const remove = async (r: Routine) => {
    if (!window.confirm(`'${r.name}' 루틴을 지울까요? 이미 쓴 문서는 드라이브에 그대로 남습니다.`)) return;
    try {
      await deleteRoutine(r.id);
      void load();
    } catch {
      toast.error("지우지 못했습니다.", { position: "top-center" });
    }
  };

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
      <PageHeader
        title="루틴"
        actions={
          ws.can("editor") && (
            <button type="button" onClick={() => setCreating(true)} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover">
              <Plus className="size-4" aria-hidden />새 루틴
            </button>
          )
        }
      />
      <div className="mx-auto flex max-w-[960px] flex-col gap-3 px-8 pb-12">
        {rows === null && <p className="py-10 text-center text-[14px] text-text-secondary">불러오는 중…</p>}
        {rows?.length === 0 && (
          <div className="rounded-[24px] bg-white px-6 py-10 text-center">
            <Repeat className="mx-auto size-8 text-neutral-300" aria-hidden />
            <p className="mt-2 text-[14px] text-text-secondary">등록한 루틴이 없습니다. AI 작업에서 "매일 7시에 … 써서 올려 줘"라고 말해도 됩니다.</p>
          </div>
        )}
        {rows?.map((r) => {
          const st = r.lastRun?.status;
          return (
            <section key={r.id} className={cn("rounded-[24px] bg-white px-6 py-5", initial === r.id && "ring-2 ring-primary/30")}>
              <div className="flex items-start gap-4">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-[16px] font-bold text-text-primary">
                    {r.name}
                    <span className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-[11px] font-medium text-neutral-600">{r.call}</span>
                    {!r.enabled && <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-text-secondary">꺼 둠</span>}
                  </p>
                  <p className="mt-0.5 text-[13px] text-text-secondary">
                    {r.formatTitle || r.formatId} · {scheduleKo(r.schedule)} · {r.recipients.all ? "전원 알림" : `알림 ${r.recipients.userIds?.length ?? 0}명`} · {r.owner.name}
                  </p>
                  {r.instruction && <p className="mt-1.5 line-clamp-2 text-[13px] text-text-primary">{r.instruction}</p>}
                  <p className="mt-2 text-[12px] text-text-secondary">
                    {st === "running" ? (
                      <span className="inline-flex items-center gap-1 text-primary">
                        <Loader2 className="size-3.5 animate-spin" aria-hidden />
                        쓰는 중
                      </span>
                    ) : r.lastRun ? (
                      <>
                        마지막 {when(r.lastRun.finishedAt ?? r.lastRun.startedAt)} · {STATUS_KO[st ?? ""] ?? st}
                        {r.lastRun.asOf && ` · ${r.lastRun.asOf} 기준`}
                        {r.lastRun.note && ` · ${r.lastRun.note}`}
                      </>
                    ) : (
                      "아직 실행 전"
                    )}
                    {r.nextRunAt && ` · 다음 ${when(r.nextRunAt)}`}
                  </p>
                  {r.lastRun?.reportId && (
                    <button type="button" onClick={() => ws.nav.openReport(r.lastRun!.reportId)} className="mt-1.5 flex cursor-pointer items-center gap-1 text-[13px] font-semibold text-primary hover:underline">
                      <FileText className="size-3.5" aria-hidden />
                      마지막으로 쓴 문서 열기
                    </button>
                  )}
                </div>
                {r.canEdit && (
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    <div className="flex gap-1">
                      <button type="button" aria-label="고치기" onClick={() => setEditing(r)} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
                        <Pencil className="size-4" aria-hidden />
                      </button>
                      <button type="button" aria-label="지우기" onClick={() => void remove(r)} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
                        <Trash2 className="size-4" aria-hidden />
                      </button>
                    </div>
                    <button type="button" disabled={st === "running" || r.manualLeft <= 0} onClick={() => void run(r)} className="flex h-8 cursor-pointer items-center gap-1 rounded-lg bg-primary px-3 text-[12px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40">
                      <Play className="size-3.5" aria-hidden />
                      지금 실행
                    </button>
                    <span className="flex items-center gap-1 rounded-lg bg-neutral-100 pl-2">
                      <CalendarClock className="size-3.5 text-neutral-500" aria-hidden />
                      <input type="date" value={asOf[r.id] ?? ""} onChange={(e) => setAsOf((m) => ({ ...m, [r.id]: e.target.value }))} aria-label="기준일" className="h-8 bg-transparent text-[12px] outline-none" />
                      <button type="button" disabled={!asOf[r.id] || st === "running" || r.manualLeft <= 0} onClick={() => void run(r, asOf[r.id])} className="h-8 cursor-pointer rounded-r-lg px-2 text-[12px] font-semibold text-neutral-700 hover:bg-neutral-200 disabled:opacity-40">
                        날짜 지정
                      </button>
                    </span>
                  </div>
                )}
              </div>
            </section>
          );
        })}
      </div>
      {(creating || editing) && (
        <RoutineDialog
          editing={editing ?? undefined}
          onClose={() => (setCreating(false), setEditing(null))}
          onSaved={() => {
            setCreating(false);
            setEditing(null);
            void load();
          }}
        />
      )}
    </div>
  );
}
