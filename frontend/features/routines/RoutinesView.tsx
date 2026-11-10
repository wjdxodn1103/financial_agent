"use client";

/**
 * AI 작업 ▸ 루틴 — 반복 업무 시간표. 위 가운데 대화창에 말하면 등록 창이 채워져 열린다(저장은 사람이 확인).
 * 왼쪽: 오늘 도는 업무를 시각순으로(완료·쓰는 중·예정) + 다가오는 실행 + 손으로만 돌리는 업무. 오른쪽: 고른 업무가 마지막으로 쓴 문서 미리보기와 쓰인 데이터.
 * 정한 시각에 만든 사람 이름으로 'AI 초안'을 써서 폴더에 올리고 알린다. [지금 실행]·[날짜 지정 실행](그날까지의 자료만).
 */
import { useCallback, useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { CalendarClock, FileText, Loader2, Pencil, Play, Plus, Repeat, Send, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ApiError } from "../report/api";
import type { ReportSource } from "../report/types";
import { useWorkspace } from "../workspace/context";
import { useOpenSource } from "../workspace/sourceHost";
import { deleteRoutine, listRoutines, proposeRoutine, runRoutine, type Routine, type RoutineInput } from "./api";
import { ReportPreview } from "./ReportPreview";
import { RoutineDialog } from "./RoutineDialog";

const WEEK = ["월", "화", "수", "목", "금", "토", "일"];
const STATUS_KO: Record<string, string> = { ok: "완료", partial: "일부만", error: "실패", running: "쓰는 중" };
const err = (e: unknown, f: string) => (e instanceof ApiError && e.status < 500 ? e.message : f);

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

const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
const sameDay = (iso: string | null | undefined, d: Date) => !!iso && dayKey(new Date(iso)) === dayKey(d);
/** 월 = 0 … 일 = 6 (서버 요일 번호와 같게) */
const weekdayOf = (d: Date) => (d.getDay() + 6) % 7;

/** 오늘 도는 업무인가(일정 기준) */
function runsToday(r: Routine, now: Date): boolean {
  const wd = weekdayOf(now);
  if (!r.enabled) return false;
  if (r.schedule.every === "daily") return true;
  if (r.schedule.every === "weekdays") return wd < 5;
  if (r.schedule.every === "weekly") return (r.schedule.weekday ?? 0) === wd;
  return false;
}

type State = "done" | "running" | "todo" | "failed";
function todayState(r: Routine, now: Date): State {
  const run = r.lastRun;
  if (run?.status === "running") return "running";
  if (run && sameDay(run.finishedAt ?? run.startedAt, now)) return run.status === "error" ? "failed" : "done";
  return "todo";
}

const CHIP: Record<State, [string, string]> = {
  done: ["완료", "bg-primary-soft text-primary-soft-foreground"],
  running: ["쓰는 중", "bg-amber-50 text-amber-700"],
  todo: ["예정", "bg-neutral-100 text-text-secondary"],
  failed: ["실패", "bg-red-50 text-destructive"],
};

function Row({ r, time, state, picked, onPick }: { r: Routine; time: string; state: State; picked: boolean; onPick: () => void }) {
  const [label, cls] = CHIP[state];
  return (
    <div className="flex items-stretch gap-3">
      <span className="num w-[76px] shrink-0 pt-[13px] text-right text-[13px] font-bold text-neutral-600">{time}</span>
      <span className="flex w-3 shrink-0 flex-col items-center" aria-hidden>
        <span className={cn("mt-[17px] size-2.5 rounded-full", state === "done" ? "bg-primary" : state === "running" ? "bg-amber-500" : "bg-neutral-300")} />
        <span className="w-0.5 flex-1 bg-neutral-200" />
      </span>
      <button
        type="button"
        onClick={onPick}
        className={cn("mb-2 flex min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-2xl bg-white px-4 py-2.5 text-left ring-1", picked ? "ring-[1.5px] ring-primary" : "ring-transparent hover:ring-neutral-200")}
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-bold text-text-primary">{r.name}</span>
          <span className="block truncate text-[12px] text-text-secondary">
            {scheduleKo(r.schedule)} · {r.formatTitle || r.formatId} · {r.recipients.all ? "팀 전체에 알림" : `알림 ${r.recipients.userIds?.length ?? 0}명`}
          </span>
        </span>
        <span className={cn("flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-bold", cls)}>
          {state === "running" && <Loader2 className="size-3 animate-spin" aria-hidden />}
          {label}
        </span>
      </button>
    </div>
  );
}

export function RoutinesView({ initial }: { initial: string | null }) {
  const ws = useWorkspace();
  const openSource = useOpenSource();
  const [rows, setRows] = useState<Routine[] | null>(null);
  const [editing, setEditing] = useState<Routine | null>(null);
  const [draft, setDraft] = useState<RoutineInput | null>(null);
  const [pickedId, setPickedId] = useState<string | null>(initial);
  const [asOf, setAsOf] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [sources, setSources] = useState<ReportSource[]>([]);
  const now = useMemo(() => new Date(), [rows]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const today = useMemo(() => (rows ?? []).filter((r) => runsToday(r, now)).sort((a, b) => a.schedule.time.localeCompare(b.schedule.time)), [rows, now]);
  const upcoming = useMemo(
    () => (rows ?? []).filter((r) => r.enabled && r.nextRunAt && !sameDay(r.nextRunAt, now)).sort((a, b) => String(a.nextRunAt).localeCompare(String(b.nextRunAt))),
    [rows, now],
  );
  const manual = useMemo(() => (rows ?? []).filter((r) => r.schedule.every === "manual" || !r.enabled), [rows]);
  const picked = rows?.find((r) => r.id === pickedId) ?? today.find((r) => r.lastRun?.reportId) ?? rows?.find((r) => r.lastRun?.reportId) ?? rows?.[0] ?? null;
  const counts = { done: today.filter((r) => todayState(r, now) === "done").length, running: today.filter((r) => todayState(r, now) === "running").length, todo: today.filter((r) => todayState(r, now) === "todo").length };

  const run = async (r: Routine, day?: string) => {
    try {
      await runRoutine(r.id, day);
      toast.success(day ? `${day} 기준으로 쓰기 시작했습니다. 끝나면 알림이 옵니다.` : "쓰기 시작했습니다. 끝나면 알림이 옵니다.", { position: "top-center" });
      window.setTimeout(() => void load(), 800);
    } catch (e) {
      toast.error(err(e, "실행하지 못했습니다."), { position: "top-center" });
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
  const propose = async () => {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    try {
      setDraft(await proposeRoutine(ws.workspaceId, t));
    } catch (e) {
      toast.error(err(e, "등록 값을 만들지 못했습니다."), { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void propose();
    }
  };

  const canAdd = ws.can("editor");
  const st = picked?.lastRun?.status;
  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
      <div className="mx-auto grid max-w-[1400px] grid-cols-[1fr_minmax(0,720px)_1fr] items-center gap-4 px-8 pt-7 pb-5">
        <h1 className="text-[24px] leading-tight font-bold tracking-tight text-text-primary">루틴</h1>
        {canAdd ? (
          <div className="flex items-end gap-2 rounded-[20px] bg-white px-4 py-2.5 ring-1 ring-primary/50">
            <Sparkles className="mb-1 size-5 shrink-0 text-primary" aria-hidden />
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={onKey}
              rows={1}
              placeholder="맡길 업무를 말해 주세요 — 예: 매일 아침 7시, 전날 증시 요약을 정해진 양식으로 올려 줘"
              className="max-h-28 min-h-6 flex-1 resize-none bg-transparent text-[14px] leading-7 font-medium outline-none placeholder:font-normal placeholder:text-neutral-400"
            />
            <button type="button" aria-label="보내기" disabled={busy || !text.trim()} onClick={() => void propose()} className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full bg-primary text-white disabled:opacity-40">
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
            </button>
          </div>
        ) : (
          <span />
        )}
        <span />
      </div>
      <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-5 px-8 pb-12 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <div className="min-w-0">
          <div className="mb-3 flex items-baseline gap-2.5">
            <h2 className="text-[18px] font-bold text-text-primary">오늘 업무</h2>
            <span className="num text-[12px] text-text-secondary">
              {now.getMonth() + 1}월 {now.getDate()}일 ({WEEK[weekdayOf(now)]}) · 완료 {counts.done}
              {counts.running > 0 && ` · 쓰는 중 ${counts.running}`} · 예정 {counts.todo}
            </span>
            {canAdd && (
              <button type="button" onClick={() => setDraft({})} className="ml-auto flex h-8 cursor-pointer items-center gap-1 rounded-lg bg-primary-soft px-2.5 text-[12px] font-bold text-primary-soft-foreground hover:bg-primary-soft-border">
                <Plus className="size-3.5" aria-hidden />
                업무 등록
              </button>
            )}
          </div>
          {rows === null && <p className="py-10 text-center text-[14px] text-text-secondary">불러오는 중…</p>}
          {rows?.length === 0 && (
            <div className="rounded-[24px] bg-white px-6 py-10 text-center">
              <Repeat className="mx-auto size-8 text-neutral-300" aria-hidden />
              <p className="mt-2 text-[14px] text-text-secondary">등록한 업무가 없습니다. 위 대화창에 &quot;매일 7시에 … 써서 올려 줘&quot;라고 말하면 됩니다.</p>
            </div>
          )}
          {rows && rows.length > 0 && today.length === 0 && <p className="mb-3 rounded-2xl bg-white px-4 py-3 text-[13px] text-text-secondary">오늘 도는 업무는 없습니다.</p>}
          {today.map((r) => (
            <Row key={r.id} r={r} time={r.schedule.time} state={todayState(r, now)} picked={picked?.id === r.id} onPick={() => setPickedId(r.id)} />
          ))}
          {upcoming.length > 0 && <h3 className="mt-4 mb-2 text-[13px] font-bold text-text-secondary">다가오는 실행</h3>}
          {upcoming.map((r) => {
            const d = new Date(r.nextRunAt as string);
            const label = `${WEEK[weekdayOf(d)]} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
            return <Row key={`n-${r.id}`} r={r} time={label} state="todo" picked={picked?.id === r.id && !today.includes(r)} onPick={() => setPickedId(r.id)} />;
          })}
          {manual.length > 0 && <h3 className="mt-4 mb-2 text-[13px] font-bold text-text-secondary">손으로 실행 · 꺼 둔 업무</h3>}
          {manual.map((r) => (
            <Row key={`m-${r.id}`} r={r} time={r.enabled ? "수동" : "꺼 둠"} state={r.lastRun?.status === "running" ? "running" : "todo"} picked={picked?.id === r.id} onPick={() => setPickedId(r.id)} />
          ))}
        </div>
        {picked && (
          <section className="min-w-0 self-start rounded-[24px] bg-white px-5 py-4">
            <div className="mb-3 flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <h2 className="truncate text-[16px] font-bold text-text-primary">{picked.name}</h2>
                <p className="num mt-0.5 truncate text-[12px] text-text-secondary">
                  {st === "running" ? (
                    "쓰는 중…"
                  ) : picked.lastRun ? (
                    <>
                      {when(picked.lastRun.finishedAt ?? picked.lastRun.startedAt)} {STATUS_KO[st ?? ""] ?? st}
                      {picked.lastRun.asOf && ` · ${picked.lastRun.asOf} 기준`} · 양식 &apos;{picked.formatTitle || picked.formatId}&apos;
                      {sources.length > 0 && ` · 쓰인 데이터 ${sources.length}건`}
                    </>
                  ) : (
                    `아직 실행 전 · 양식 '${picked.formatTitle || picked.formatId}'`
                  )}
                  {picked.nextRunAt && ` · 다음 ${when(picked.nextRunAt)}`}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {picked.lastRun?.reportId && (
                  <button type="button" onClick={() => ws.nav.openReport(picked.lastRun!.reportId)} className="flex h-8 cursor-pointer items-center gap-1 rounded-lg bg-primary-soft px-2.5 text-[12px] font-bold text-primary-soft-foreground hover:bg-primary-soft-border">
                    <FileText className="size-3.5" aria-hidden />
                    문서 열기
                  </button>
                )}
                {picked.canEdit && (
                  <>
                    <button type="button" disabled={st === "running" || picked.manualLeft <= 0} onClick={() => void run(picked)} className="flex h-8 cursor-pointer items-center gap-1 rounded-lg bg-primary px-2.5 text-[12px] font-bold text-white hover:bg-primary-hover disabled:opacity-40">
                      <Play className="size-3.5" aria-hidden />
                      지금 실행
                    </button>
                    <span className="flex items-center gap-1 rounded-lg bg-neutral-100 pl-2">
                      <CalendarClock className="size-3.5 text-neutral-500" aria-hidden />
                      <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} aria-label="기준일" className="h-8 w-[112px] bg-transparent text-[12px] outline-none" />
                      <button type="button" disabled={!asOf || st === "running" || picked.manualLeft <= 0} onClick={() => void run(picked, asOf)} className="h-8 cursor-pointer rounded-r-lg px-2 text-[12px] font-semibold text-neutral-700 hover:bg-neutral-200 disabled:opacity-40">
                        날짜 지정
                      </button>
                    </span>
                    <button type="button" aria-label="고치기" onClick={() => setEditing(picked)} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
                      <Pencil className="size-4" aria-hidden />
                    </button>
                    <button type="button" aria-label="지우기" onClick={() => void remove(picked)} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
                      <Trash2 className="size-4" aria-hidden />
                    </button>
                  </>
                )}
              </div>
            </div>
            {picked.lastRun?.reportId ? (
              <>
                <ReportPreview key={picked.lastRun.reportId} reportId={picked.lastRun.reportId} onLoaded={(s) => setSources(s)} />
                {sources.length > 0 && (
                  <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-text-secondary">
                    <b className="font-bold text-text-primary">쓰인 데이터</b>
                    {sources.slice(0, 6).map((s) => (
                      <button key={s.docId} type="button" onClick={() => openSource(s.docId)} className="cursor-pointer truncate rounded-md bg-neutral-100 px-1.5 py-0.5 hover:bg-primary-soft hover:text-primary">
                        <span className="font-bold text-primary">[{s.n}]</span> {s.label}
                      </button>
                    ))}
                    {sources.length > 6 && <span>외 {sources.length - 6}건</span>}
                  </p>
                )}
              </>
            ) : (
              <div className="rounded-xl border border-dashed border-neutral-200 px-5 py-10 text-center text-[13px] text-text-secondary">
                {picked.instruction && <p className="mx-auto mb-2 max-w-[520px] text-text-primary">{picked.instruction}</p>}
                {picked.lastRun?.note || "아직 쓴 문서가 없습니다. 정한 시각이 되면 쓰거나, [지금 실행]으로 바로 쓸 수 있습니다."}
              </div>
            )}
          </section>
        )}
      </div>
      {(draft || editing) && (
        <RoutineDialog
          initial={draft && Object.keys(draft).length ? draft : undefined}
          editing={editing ?? undefined}
          onClose={() => (setDraft(null), setEditing(null))}
          onSaved={(r) => {
            setDraft(null);
            setEditing(null);
            setText("");
            setPickedId(r.id);
            void load();
          }}
        />
      )}
    </div>
  );
}
