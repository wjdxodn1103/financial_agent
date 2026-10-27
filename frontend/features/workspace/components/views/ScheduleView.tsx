"use client";

/**
 * 일정 — 월 달력과 타임라인(담당자별). 작업 항목의 기간(시작~마감)이 날짜를 가로지르는 막대로 이어진다.
 * 막대를 끌면 기간이 통째로 옮겨지고, 양 끝을 끌면 시작·마감이 바뀐다. 누르면 상세. 보기: 전체 일정 / 내 일정.
 * 달력은 날짜 칸의 '+', 타임라인은 담당자 줄의 '+'로 새 작업을 만든다(타임라인에서 날짜 없는 작업은 칸을 눌러 날짜를 준다).
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as RPointerEvent } from "react";
import { CalendarDays, ChartGantt, ChevronDown, ChevronLeft, ChevronRight, Plus, User, Users } from "lucide-react";

import { cn } from "@/lib/utils";
import { useWorkspace } from "../../context";
import { useTasks } from "../../hooks/useTasks";
import type { TaskItem } from "../../types";
import { Avatar, STATUS, TaskDialog, draftTask, rangeText, ymd } from "./taskParts";

const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];
/** 타임라인 날짜 칸 너비·왼쪽 이름 칸 너비(px) */
const COL = 44;
const LEFT = 248;

const parse = (s: string) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};
const shift = (s: string, n: number) => {
  const d = parse(s);
  d.setDate(d.getDate() + n);
  return ymd(d);
};
const diff = (a: string, b: string) => Math.round((parse(b).getTime() - parse(a).getTime()) / 86400000);
const spanOf = (t: TaskItem) => ({ s: t.start || t.due, e: t.due });

type Mode = "move" | "start" | "end";
type Span = { s: string; e: string };

function applyGrab(t: TaskItem, mode: Mode, d: number): Span {
  const { s, e } = spanOf(t);
  if (mode === "move") return { s: shift(s, d), e: shift(e, d) };
  if (mode === "start") {
    const ns = shift(s, d);
    return { s: ns > e ? e : ns, e };
  }
  const ne = shift(e, d);
  return { s, e: ne < s ? s : ne };
}

/** 포인터 아래 날짜 칸(data-day) */
function dayAt(x: number, y: number): string | null {
  for (const el of document.elementsFromPoint(x, y)) {
    const d = (el as HTMLElement).dataset?.day;
    if (d) return d;
  }
  return null;
}

/** 막대 끌기(옮기기·늘이기) — 끄는 동안은 미리 보기만, 놓을 때 저장. 움직이지 않고 놓으면 누른 것으로 본다 */
function useBarDrag(onDrop: (t: TaskItem, span: Span) => void) {
  const [grab, setGrab] = useState<{ t: TaskItem; mode: Mode } | null>(null);
  const [delta, setDelta] = useState(0);
  const moved = useRef(false);
  const dropRef = useRef(onDrop);
  useEffect(() => {
    dropRef.current = onDrop;
  }, [onDrop]);

  return {
    grabbing: grab?.t.id ?? null,
    live: (t: TaskItem): Span => (grab && grab.t.id === t.id ? applyGrab(t, grab.mode, delta) : spanOf(t)),
    /** 누르는 순간 창에 움직임·놓기 듣기를 건다(빠른 끌기도 놓치지 않게) */
    start: (t: TaskItem, mode: Mode) => (e: RPointerEvent) => {
      if (e.button !== 0) return;
      e.stopPropagation();
      const from = dayAt(e.clientX, e.clientY);
      if (!from) return;
      const x0 = e.clientX;
      const y0 = e.clientY;
      let d = 0;
      moved.current = false;
      setDelta(0);
      setGrab({ t, mode });
      document.body.style.cursor = mode === "move" ? "grabbing" : "ew-resize";
      const move = (ev: PointerEvent) => {
        if (Math.abs(ev.clientX - x0) + Math.abs(ev.clientY - y0) > 4) moved.current = true;
        const day = dayAt(ev.clientX, ev.clientY);
        if (day && diff(from, day) !== d) {
          d = diff(from, day);
          setDelta(d);
        }
      };
      const end = (ev: PointerEvent) => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", end);
        window.removeEventListener("pointercancel", end);
        document.body.style.cursor = "";
        setGrab(null);
        setDelta(0);
        if (ev.type === "pointerup" && moved.current && d !== 0) dropRef.current(t, applyGrab(t, mode, d));
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", end);
      window.addEventListener("pointercancel", end);
    },
    /** 막대 onClick — 끌었던 것이면 무시 */
    clicked: () => !moved.current,
  };
}

type Drag = ReturnType<typeof useBarDrag>;

function Bar({ t, span, from, to, drag, editable, onOpen, avatar, className, style }: { t: TaskItem; span: Span; from: string; to: string; drag: Drag; editable: boolean; onOpen: () => void; avatar: boolean; className?: string; style: CSSProperties }) {
  const st = STATUS.find((s) => s.id === t.status);
  const clipL = span.s < from;
  const clipR = span.e > to;
  return (
    <div
      role="button"
      tabIndex={0}
      title={`${t.title} · ${rangeText(span.s === span.e ? "" : span.s, span.e)}`}
      onPointerDown={editable ? drag.start(t, "move") : undefined}
      onClick={() => drag.clicked() && onOpen()}
      onKeyDown={(e) => e.key === "Enter" && onOpen()}
      style={style}
      className={cn(
        "pointer-events-auto absolute flex items-center gap-1 overflow-hidden px-2 text-[12px] font-medium select-none transition-colors",
        st?.bar,
        clipL ? "rounded-l-none" : "rounded-l-full",
        clipR ? "rounded-r-none" : "rounded-r-full",
        editable ? "cursor-grab" : "cursor-pointer",
        drag.grabbing === t.id && "z-10 shadow-[0_4px_12px_rgba(0,27,55,0.18)]",
        className,
      )}
    >
      {avatar && t.assigneeId && <Avatar userId={t.assigneeId} size={16} />}
      <span className="min-w-0 truncate">{t.title}</span>
      {editable && !clipL && <span onPointerDown={drag.start(t, "start")} className="absolute inset-y-0 left-0 w-2 cursor-ew-resize" aria-hidden />}
      {editable && !clipR && <span onPointerDown={drag.start(t, "end")} className="absolute inset-y-0 right-0 w-2 cursor-ew-resize" aria-hidden />}
    </div>
  );
}

export function ScheduleView() {
  const ws = useWorkspace();
  const t = useTasks();
  const [mode, setMode] = useState<"calendar" | "timeline">("calendar");
  const [month, setMonth] = useState(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });
  const [view, setView] = useState<"all" | "mine">("all");
  const [open, setOpen] = useState<TaskItem | null>(null);
  const drag = useBarDrag((task, span) => void t.setDates(task, span.s, span.e));
  const shown = useMemo(() => t.tasks.filter((x) => view === "all" || x.assigneeId === ws.me.id), [t.tasks, view, ws.me.id]);
  const now = new Date();
  const thisMonth = now.getFullYear() === month.getFullYear() && now.getMonth() === month.getMonth();
  const step = (n: number) => setMonth((m) => new Date(m.getFullYear(), m.getMonth() + n, 1));
  const add = (patch: Partial<TaskItem>) => setOpen(draftTask({ assigneeId: ws.me.id, ...patch }));

  return (
    <div className={cn("thin-scrollbar min-h-0 flex-1 overflow-auto bg-white", drag.grabbing && "select-none")}>
      <div className="px-8 pt-8 pb-10">
        <h1 className="flex items-center gap-2.5 text-[26px] leading-tight font-bold tracking-tight text-text-primary">
          <CalendarDays className="size-7 text-primary" aria-hidden />
          일정
        </h1>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-b border-neutral-100 pb-2">
          <div className="flex items-center gap-1">
            {(
              [
                ["all", "전체 일정", Users],
                ["mine", "내 일정", User],
              ] as const
            ).map(([id, label, Icon]) => (
              <button key={id} type="button" onClick={() => setView(id)} className={cn("flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1.5 text-[14px] font-medium transition-colors", view === id ? "bg-neutral-100 text-text-primary" : "text-neutral-500 hover:bg-neutral-50")}>
                <Icon className="size-4" aria-hidden />
                {label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <div className="flex rounded-xl bg-neutral-100 p-1">
              {(
                [
                  ["calendar", "달력", CalendarDays],
                  ["timeline", "타임라인", ChartGantt],
                ] as const
              ).map(([id, label, Icon]) => (
                <button key={id} type="button" onClick={() => setMode(id)} className={cn("flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1 text-[13px] font-semibold transition-colors", mode === id ? "bg-white text-text-primary shadow-sm" : "text-neutral-500 hover:text-neutral-700")}>
                  <Icon className="size-4" aria-hidden />
                  {label}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1">
              {!thisMonth && (
                <button type="button" onClick={() => setMonth(new Date(now.getFullYear(), now.getMonth(), 1))} className="mr-1 h-8 cursor-pointer rounded-lg bg-neutral-100 px-3 text-[13px] font-semibold text-neutral-700 hover:bg-neutral-200">
                  오늘
                </button>
              )}
              <button type="button" aria-label="이전 달" onClick={() => step(-1)} className="cursor-pointer rounded-lg p-1.5 text-neutral-600 hover:bg-neutral-100">
                <ChevronLeft className="size-5" aria-hidden />
              </button>
              <span className="min-w-[110px] text-center text-[16px] font-bold text-text-primary tabular-nums">
                {month.getFullYear()}년 {month.getMonth() + 1}월
              </span>
              <button type="button" aria-label="다음 달" onClick={() => step(1)} className="cursor-pointer rounded-lg p-1.5 text-neutral-600 hover:bg-neutral-100">
                <ChevronRight className="size-5" aria-hidden />
              </button>
            </div>
          </div>
        </div>

        {mode === "calendar" ? (
          <MonthCalendar month={month} tasks={shown} drag={drag} canEdit={t.canEdit} onOpen={setOpen} onAdd={(day) => add({ due: day })} />
        ) : (
          <Timeline
            month={month}
            tasks={shown}
            mine={view === "mine"}
            drag={drag}
            canEdit={t.canEdit}
            canAddFor={(uid) => t.editor || uid === ws.me.id}
            onOpen={setOpen}
            onAdd={(uid) => add({ assigneeId: uid, due: thisMonth ? ymd(now) : ymd(month) })}
            onPlace={(task, day) => void t.setDates(task, day, day)}
          />
        )}
        {t.loading && <p className="mt-4 text-[14px] text-neutral-500">불러오는 중…</p>}
      </div>
      {open && (
        <TaskDialog
          t={open}
          canEdit={!open.id || t.canEdit(open)}
          canMove={open.id ? t.canMove(open) : t.editor || ws.can("reviewer")}
          onClose={() => setOpen(null)}
          onSave={(body) => (open.id ? t.save(open, body) : t.create(body.title ?? "", { status: body.status, due: body.due, start: body.start, assigneeId: body.assigneeId, detail: body.detail }))}
          onRemove={open.id ? () => t.remove(open) : undefined}
          onOpenReport={(id) => ws.nav.openReport(id)}
        />
      )}
    </div>
  );
}

/** 월 달력 — 일요일부터 한 주씩 줄. 기간 막대는 주 경계에서 끊겨 다음 줄로 이어진다 */
function MonthCalendar({ month, tasks, drag, canEdit, onOpen, onAdd }: { month: Date; tasks: TaskItem[]; drag: Drag; canEdit: (t: TaskItem) => boolean; onOpen: (t: TaskItem) => void; onAdd: (day: string) => void }) {
  const today = ymd(new Date());
  const first = ymd(month);
  const gridStart = shift(first, -month.getDay());
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const weeks = Math.ceil((month.getDay() + days) / 7);
  const dated = tasks.filter((x) => x.due);
  const LANE = 26;
  const TOP = 34;

  return (
    <div className="mt-4 overflow-hidden rounded-2xl border border-neutral-200">
      <div className="grid grid-cols-7 border-b border-neutral-200 bg-white">
        {WEEKDAY.map((w, i) => (
          <span key={w} className={cn("py-2.5 text-center text-[13px] font-semibold", i === 0 || i === 6 ? "text-neutral-400" : "text-neutral-600")}>
            {w}
          </span>
        ))}
      </div>
      {Array.from({ length: weeks }, (_, w) => {
        const from = shift(gridStart, w * 7);
        const to = shift(from, 6);
        const bars = dated
          .map((x) => ({ x, span: drag.live(x) }))
          .filter(({ span }) => span.s <= to && span.e >= from)
          .sort((a, b) => a.span.s.localeCompare(b.span.s) || diff(b.span.s, b.span.e) - diff(a.span.s, a.span.e) || a.x.title.localeCompare(b.x.title));
        const ends: string[] = [];
        const placed = bars.map((b) => {
          let lane = ends.findIndex((e) => e < b.span.s);
          if (lane < 0) lane = ends.length;
          ends[lane] = b.span.e;
          return { ...b, lane };
        });
        return (
          <div key={from} className="relative border-b border-neutral-100 last:border-b-0" style={{ minHeight: Math.max(118, TOP + ends.length * LANE + 10) }}>
            <div className="absolute inset-0 grid grid-cols-7">
              {Array.from({ length: 7 }, (_, i) => {
                const key = shift(from, i);
                const inMonth = key.slice(0, 7) === first.slice(0, 7);
                const isToday = key === today;
                return (
                  <div key={key} data-day={key} className={cn("group/cell border-r border-neutral-100 last:border-r-0", !inMonth && "bg-neutral-50/70", isToday && "bg-primary-soft/40")}>
                    <div className="flex items-center justify-between px-2 pt-1.5">
                      <span className={cn("num flex size-6 items-center justify-center rounded-full text-[13px] font-semibold", isToday ? "bg-primary text-white" : !inMonth ? "text-neutral-300" : i === 0 || i === 6 ? "text-neutral-400" : "text-neutral-700")}>{Number(key.slice(8))}</span>
                      <button type="button" aria-label={`${key} 새 작업`} onClick={() => onAdd(key)} className="cursor-pointer rounded-md p-0.5 text-neutral-400 opacity-0 group-hover/cell:opacity-100 hover:bg-neutral-100 hover:text-neutral-700">
                        <Plus className="size-4" aria-hidden />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="pointer-events-none absolute inset-x-0" style={{ top: TOP }}>
              {placed.map(({ x, span, lane }) => {
                const c0 = Math.max(0, diff(from, span.s));
                const c1 = Math.min(6, diff(from, span.e));
                const l = span.s < from ? 0 : 4;
                const r = span.e > to ? 0 : 4;
                return (
                  <Bar
                    key={x.id}
                    t={x}
                    span={span}
                    from={from}
                    to={to}
                    drag={drag}
                    editable={canEdit(x)}
                    onOpen={() => onOpen(x)}
                    avatar
                    className="h-[22px]"
                    style={{ top: lane * LANE, left: `calc(${c0} * 100% / 7 + ${l}px)`, width: `calc(${c1 - c0 + 1} * 100% / 7 - ${l + r}px)` }}
                  />
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** 타임라인 — 담당자별로 묶은 줄, 이달 날짜 칸 위에 기간 막대. 묶음 줄의 가는 선 = 그 사람 작업 전체 기간 */
function Timeline({ month, tasks, mine, drag, canEdit, canAddFor, onOpen, onAdd, onPlace }: { month: Date; tasks: TaskItem[]; mine: boolean; drag: Drag; canEdit: (t: TaskItem) => boolean; canAddFor: (userId: string | null) => boolean; onOpen: (t: TaskItem) => void; onAdd: (userId: string | null) => void; onPlace: (t: TaskItem, day: string) => void }) {
  const ws = useWorkspace();
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const today = ymd(new Date());
  const first = ymd(month);
  const n = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const days = useMemo(() => Array.from({ length: n }, (_, i) => shift(first, i)), [first, n]);
  const from = days[0];
  const to = days[n - 1];
  const members = ws.detail?.members;
  const scroller = useRef<HTMLDivElement>(null);

  // 이달이면 오늘이 왼쪽 가까이 보이게
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollLeft = today >= from && today <= to ? Math.max(0, diff(from, today) - 3) * COL : 0;
  }, [from, to, today]);

  const groups = useMemo(() => {
    const ids = (members ?? []).map((m) => m.user.id);
    const order = mine ? [ws.me.id] : [ws.me.id, ...ids.filter((id) => id !== ws.me.id)];
    const list: { id: string | null; tasks: TaskItem[] }[] = order.map((id) => ({ id, tasks: tasks.filter((x) => x.assigneeId === id) }));
    const rest = tasks.filter((x) => !x.assigneeId || !order.includes(x.assigneeId));
    if (!mine && rest.length) list.push({ id: null, tasks: rest });
    const key = (x: TaskItem) => (x.due ? spanOf(x).s : "9999");
    return list.map((g) => ({ ...g, tasks: g.tasks.filter((x) => !x.due || (spanOf(x).s <= to && x.due >= from)).sort((a, b) => key(a).localeCompare(key(b)) || a.title.localeCompare(b.title)) }));
  }, [tasks, members, ws.me.id, mine, from, to]);

  const pos = (span: Span, inset: number) => {
    const c0 = Math.max(0, diff(from, span.s));
    const c1 = Math.min(n - 1, diff(from, span.e));
    const l = span.s < from ? 0 : inset;
    const r = span.e > to ? 0 : inset;
    return { left: c0 * COL + l, width: (c1 - c0 + 1) * COL - l - r };
  };

  /** 날짜 칸 줄 — 날짜 없는 작업 줄이면 칸을 눌러 그날로 둔다 */
  const grid = (undated?: TaskItem) => (
    <div className="absolute inset-0 flex">
      {days.map((k) => {
        const wd = parse(k).getDay();
        return (
          <div
            key={k}
            data-day={k}
            onClick={undated ? () => onPlace(undated, k) : undefined}
            title={undated ? `${Number(k.slice(5, 7))}월 ${Number(k.slice(8))}일로 두기` : undefined}
            style={{ width: COL }}
            className={cn("shrink-0 border-r border-neutral-100", k === today ? "bg-primary-soft/40" : (wd === 0 || wd === 6) && "bg-neutral-50", undated && "cursor-pointer hover:bg-primary-soft")}
          />
        );
      })}
    </div>
  );

  return (
    <div ref={scroller} className="thin-scrollbar mt-4 overflow-x-auto rounded-2xl border border-neutral-200">
      <div style={{ width: LEFT + n * COL }}>
        <div className="flex border-b border-neutral-200">
          <div className="sticky left-0 z-20 shrink-0 border-r border-neutral-200 bg-white" style={{ width: LEFT }} />
          {days.map((k) => {
            const wd = parse(k).getDay();
            return (
              <div key={k} style={{ width: COL }} className="flex shrink-0 flex-col items-center py-1.5">
                <span className={cn("text-[11px] font-medium", wd === 0 || wd === 6 ? "text-neutral-300" : "text-neutral-400")}>{WEEKDAY[wd]}</span>
                <span className={cn("num flex size-7 items-center justify-center rounded-full text-[13px] font-semibold", k === today ? "bg-primary text-white" : wd === 0 || wd === 6 ? "text-neutral-400" : "text-neutral-700")}>{Number(k.slice(8))}</span>
              </div>
            );
          })}
        </div>

        {groups.map((g) => {
          const key = g.id ?? "none";
          const isOpen = !closed.has(key);
          const spans = g.tasks.filter((x) => x.due).map((x) => drag.live(x));
          const sum = spans.length ? { s: spans.reduce((a, b) => (b.s < a ? b.s : a), spans[0].s), e: spans.reduce((a, b) => (b.e > a ? b.e : a), spans[0].e) } : null;
          return (
            <div key={key} className="border-b border-neutral-100 last:border-b-0">
              <div className="group/row flex h-11">
                <div className="sticky left-0 z-20 flex shrink-0 items-center gap-2 border-r border-neutral-200 bg-white px-2.5" style={{ width: LEFT }}>
                  <button
                    type="button"
                    aria-label={isOpen ? "접기" : "펼치기"}
                    onClick={() =>
                      setClosed((c) => {
                        const next = new Set(c);
                        if (next.has(key)) next.delete(key);
                        else next.add(key);
                        return next;
                      })
                    }
                    className="cursor-pointer rounded-md p-0.5 text-neutral-500 hover:bg-neutral-100"
                  >
                    <ChevronDown className={cn("size-4 transition-transform", !isOpen && "-rotate-90")} aria-hidden />
                  </button>
                  {g.id ? <Avatar userId={g.id} size={22} /> : <span className="size-[22px] shrink-0 rounded-full bg-neutral-200" />}
                  <span className="min-w-0 truncate text-[14px] font-semibold text-text-primary">{g.id ? ws.nameOf(g.id) : "담당 없음"}</span>
                  <span className="text-[12px] font-semibold text-neutral-400">{g.tasks.length}</span>
                  {canAddFor(g.id) && (
                    <button type="button" aria-label="새 작업" onClick={() => onAdd(g.id)} className="ml-auto cursor-pointer rounded-md p-0.5 text-neutral-400 opacity-0 group-hover/row:opacity-100 hover:bg-neutral-100 hover:text-neutral-700">
                      <Plus className="size-4" aria-hidden />
                    </button>
                  )}
                </div>
                <div className="relative flex-1">
                  {grid()}
                  {sum && sum.s <= to && sum.e >= from && <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-neutral-300" style={pos(sum, 6)} />}
                </div>
              </div>
              {isOpen &&
                g.tasks.map((x) => {
                  const st = STATUS.find((s) => s.id === x.status);
                  const span = drag.live(x);
                  return (
                    <div key={x.id} className="flex h-10">
                      <button type="button" onClick={() => onOpen(x)} className="sticky left-0 z-20 flex shrink-0 cursor-pointer items-center gap-2 border-r border-neutral-200 bg-white pr-2.5 pl-10 text-left hover:bg-neutral-50" style={{ width: LEFT }}>
                        <span className={cn("size-2 shrink-0 rounded-full", st?.dot)} aria-hidden />
                        <span className={cn("min-w-0 truncate text-[13px]", x.status === "done" ? "text-neutral-400 line-through" : "text-text-primary")}>{x.title}</span>
                        {!x.due && <span className="ml-auto shrink-0 text-[11px] text-neutral-400">날짜 없음</span>}
                      </button>
                      <div className="relative flex-1">
                        {grid(!x.due && canEdit(x) ? x : undefined)}
                        {x.due && span.s <= to && span.e >= from && (
                          <div className="pointer-events-none absolute inset-0">
                            <Bar t={x} span={span} from={from} to={to} drag={drag} editable={canEdit(x)} onOpen={() => onOpen(x)} avatar={false} className="top-1.5 h-7" style={pos(span, 3)} />
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
