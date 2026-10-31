"use client";

/**
 * 대시보드 ▸ 경제 일정 — 리서치 캘린더(월간·주간, KB 형식) · 일정표(시간·국가·중요도·실제·예상·이전, investing 형식) · 내 알림.
 * 일정은 전사 공용(BE app/calendar — FRED 발표일·공식 일정표·만기 규칙). 시각은 한국 기준, 미국·유럽은 현지 시각을 함께.
 * 발표가 감지되면 서버가 양식대로 만든 메시지를 보낸다(AI 없음). 채팅으로 "…발표되면 알려 줘" 하면 확인 카드로 등록.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Bell, BellRing, ChevronLeft, ChevronRight, ExternalLink, Loader2, RefreshCw, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError } from "../report/api";
import { useWorkspace } from "../workspace/context";
import { PageHeader } from "../workspace/components/views/PageHeader";
import {
  createEventAlerts,
  deleteEventAlert,
  fmtValue,
  getCalendar,
  getCalendarMeta,
  listEventAlerts,
  putActual,
  setForecast,
  syncCalendar,
  type CalendarMeta,
  type EventAlertView,
  type KeyStatus,
  type MarketEventView,
} from "./api";

type Tab = "month" | "week" | "list" | "alerts";
const COUNTRIES = [
  ["", "전체"],
  ["KR", "한국"],
  ["US", "미국"],
  ["EU", "유럽"],
  ["CN", "중국"],
] as const;
const CATEGORIES = [
  ["release", "발표"],
  ["meeting", "회의"],
  ["issue", "이슈"],
  ["industry", "산업"],
  ["earnings", "실적"],
  ["holiday", "휴장"],
] as const;
const IMPORTANCE = [
  [3, "★★★"],
  [2, "★★ 이상"],
  [1, "전부"],
] as const;
const WEEK = ["일", "월", "화", "수", "목", "금", "토"];

const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const stars = (n: number) => "★".repeat(n) + "☆".repeat(Math.max(0, 3 - n));

function range(tab: Tab, cursor: Date): [Date, Date] {
  if (tab === "week") {
    const s = addDays(cursor, -cursor.getDay());
    return [s, addDays(s, 6)];
  }
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const last = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
  return tab === "month" ? [addDays(first, -first.getDay()), addDays(last, 6 - last.getDay())] : [first, last];
}

export function CalendarView({ initial }: { initial?: string | null }) {
  const ws = useWorkspace();
  const [tab, setTab] = useState<Tab>("month");
  const [cursor, setCursor] = useState(() => new Date());
  const [country, setCountry] = useState("");
  const [cats, setCats] = useState<string[]>([]);
  const [minImp, setMinImp] = useState(2);
  const [events, setEvents] = useState<MarketEventView[] | null>(null);
  const [keys, setKeys] = useState<KeyStatus | null>(null);
  const [meta, setMeta] = useState<CalendarMeta | null>(null);
  const [day, setDay] = useState(() => ymd(new Date()));
  const [openId, setOpenId] = useState<string | null>(initial ?? null);
  const [alerts, setAlerts] = useState<EventAlertView[] | null>(null);
  const [syncing, setSyncing] = useState(false);

  const [s, e] = range(tab === "alerts" ? "month" : tab, cursor);
  const load = useCallback(() => {
    getCalendar(ws.workspaceId, { start: ymd(s), end: ymd(e), country, category: cats.join(","), minImportance: minImp }).then(
      (r) => (setEvents(r.events), setKeys(r.keys)),
      () => setEvents([]),
    );
  }, [ws.workspaceId, s.getTime(), e.getTime(), country, cats.join(","), minImp]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(load, [load]);
  useEffect(() => {
    getCalendarMeta().then(setMeta, () => undefined);
  }, []);
  const loadAlerts = useCallback(() => void listEventAlerts(ws.workspaceId).then(setAlerts, () => setAlerts([])), [ws.workspaceId]);
  useEffect(loadAlerts, [loadAlerts]);

  const byDay = useMemo(() => {
    const m = new Map<string, MarketEventView[]>();
    for (const ev of events ?? []) m.set(ev.date, [...(m.get(ev.date) ?? []), ev]);
    return m;
  }, [events]);
  const open = events?.find((x) => x.id === openId) ?? null;
  const replace = (ev: MarketEventView) => setEvents((xs) => xs?.map((x) => (x.id === ev.id ? ev : x)) ?? xs);

  const move = (n: number) => setCursor((c) => (tab === "week" ? addDays(c, 7 * n) : new Date(c.getFullYear(), c.getMonth() + n, 1)));
  const title = tab === "week" ? `${s.getMonth() + 1}월 ${s.getDate()}일 – ${e.getMonth() + 1}월 ${e.getDate()}일` : `${cursor.getFullYear()}년 ${cursor.getMonth() + 1}월`;

  const resync = async () => {
    setSyncing(true);
    try {
      const r = await syncCalendar();
      toast.success(`일정 ${r.added}건 새로 · ${r.updated}건 고침${r.errors.length ? ` · 오류 ${r.errors.length}` : ""}`, { position: "top-center" });
      load();
    } catch {
      toast.error("일정을 다시 받지 못했습니다.", { position: "top-center" });
    } finally {
      setSyncing(false);
    }
  };

  const keyLine = keys ? [`BLS ${keys.bls ? "키" : `키 없음(오늘 ${keys.blsLeft}회 남음)`}`, `FRED ${keys.fred ? "키" : "키 없음"}`, `ECOS ${keys.ecos ? "키" : "키 없음"}`].join(" · ") : undefined;

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
      <PageHeader
        title="경제 일정"
        wide
        desc={keyLine && `발표 감지: ${keyLine}`}
        actions={
          meta?.isAdmin && (
            <button type="button" disabled={syncing} onClick={() => void resync()} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-white px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-50 disabled:opacity-60">
              {syncing ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <RefreshCw className="size-4" aria-hidden />}
              일정 다시 받기
            </button>
          )
        }
      />
      <div className="mx-auto max-w-[1180px] px-8 pb-14">
        <div className="flex flex-wrap items-center gap-2">
          <Seg value={tab} onChange={(v) => setTab(v as Tab)} items={[["month", "월간"], ["week", "주간"], ["list", "일정표"], ["alerts", `내 알림${alerts?.length ? ` ${alerts.length}` : ""}`]]} />
          {tab !== "alerts" && (
            <>
              <span className="ml-2 flex items-center gap-1">
                <IconBtn label="이전" onClick={() => move(-1)}>
                  <ChevronLeft className="size-4" aria-hidden />
                </IconBtn>
                <span className="min-w-[150px] text-center text-[15px] font-bold text-text-primary">{title}</span>
                <IconBtn label="다음" onClick={() => move(1)}>
                  <ChevronRight className="size-4" aria-hidden />
                </IconBtn>
                <button type="button" onClick={() => (setCursor(new Date()), setDay(ymd(new Date())))} className="ml-1 h-8 cursor-pointer rounded-lg bg-white px-2.5 text-[12px] text-text-secondary hover:text-text-primary">
                  오늘
                </button>
              </span>
              <span className="ml-auto flex flex-wrap items-center gap-2">
                <Seg value={country} onChange={setCountry} items={COUNTRIES.map(([k, l]) => [k, l])} />
                <Seg value={String(minImp)} onChange={(v) => setMinImp(Number(v))} items={IMPORTANCE.map(([k, l]) => [String(k), l])} />
              </span>
            </>
          )}
        </div>
        {tab !== "alerts" && (
          <div className="mt-2 flex flex-wrap items-center gap-1">
            {CATEGORIES.map(([k, l]) => {
              const on = cats.includes(k);
              return (
                <button key={k} type="button" onClick={() => setCats((c) => (on ? c.filter((x) => x !== k) : [...c, k]))} className={cn("h-7 cursor-pointer rounded-full px-3 text-[12px]", on ? "bg-neutral-800 text-white" : "bg-white text-text-secondary hover:text-text-primary")}>
                  {l}
                </button>
              );
            })}
            {cats.length > 0 && (
              <button type="button" onClick={() => setCats([])} className="h-7 cursor-pointer px-2 text-[12px] text-text-secondary underline">
                분류 전부
              </button>
            )}
          </div>
        )}

        <div className="mt-3">
          {events === null && tab !== "alerts" && <p className="text-[13px] text-text-secondary">불러오는 중…</p>}
          {events && tab === "month" && (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
              <MonthGrid start={s} end={e} month={cursor.getMonth()} byDay={byDay} day={day} onDay={setDay} onOpen={setOpenId} />
              <DayList date={day} events={byDay.get(day) ?? []} onOpen={setOpenId} />
            </div>
          )}
          {events && tab === "week" && <WeekCols start={s} byDay={byDay} onOpen={setOpenId} />}
          {events && tab === "list" && <Table events={events} onOpen={setOpenId} />}
          {tab === "alerts" && <AlertList alerts={alerts} onOpen={setOpenId} onDeleted={loadAlerts} />}
        </div>
      </div>
      {open && (
        <EventDrawer
          ev={open}
          keys={keys}
          isAdmin={!!meta?.isAdmin}
          onClose={() => setOpenId(null)}
          onChange={(x) => (replace(x), loadAlerts())}
          onAlerted={() => (load(), loadAlerts())}
        />
      )}
    </div>
  );
}

function Seg({ value, onChange, items }: { value: string; onChange: (v: string) => void; items: readonly (readonly [string, string])[] }) {
  return (
    <div className="flex items-center gap-0.5 rounded-xl bg-white p-1">
      {items.map(([k, l]) => (
        <button key={k} type="button" onClick={() => onChange(k)} className={cn("h-7 cursor-pointer rounded-lg px-2.5 text-[12px]", k === value ? "bg-neutral-100 font-semibold text-text-primary" : "text-text-secondary hover:text-text-primary")}>
          {l}
        </button>
      ))}
    </div>
  );
}

function IconBtn({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} className="flex size-8 cursor-pointer items-center justify-center rounded-lg bg-white text-text-secondary hover:text-text-primary">
      {children}
    </button>
  );
}

/** 칸 한 줄 — '22:30 미국 CPI' (시각 모르면 이름만), 중요도 3은 굵게 */
function Chip({ ev, onOpen }: { ev: MarketEventView; onOpen: (id: string) => void }) {
  return (
    <button
      type="button"
      onClick={(e) => (e.stopPropagation(), onOpen(ev.id))}
      title={`${ev.countryKo} ${ev.title}${ev.period ? ` · ${ev.period}` : ""}`}
      className={cn("flex w-full cursor-pointer items-center gap-1 truncate rounded px-1 text-left text-[11px] leading-5 hover:bg-neutral-100", ev.importance >= 3 ? "font-semibold text-text-primary" : "text-text-secondary")}
    >
      {ev.alerted && <BellRing className="size-3 shrink-0" aria-hidden />}
      {ev.kstTime && <span className="shrink-0 tabular-nums">{ev.kstTime}</span>}
      <span className="truncate">
        {ev.countryKo} {ev.short}
        {ev.status === "released" && ev.category !== "holiday" && " ✓"}
      </span>
    </button>
  );
}

function MonthGrid({ start, end, month, byDay, day, onDay, onOpen }: { start: Date; end: Date; month: number; byDay: Map<string, MarketEventView[]>; day: string; onDay: (d: string) => void; onOpen: (id: string) => void }) {
  const days: Date[] = [];
  for (let d = start; d <= end; d = addDays(d, 1)) days.push(d);
  const today = ymd(new Date());
  return (
    <div className="overflow-hidden rounded-[20px] bg-white">
      <div className="grid grid-cols-7 border-b border-neutral-100 text-center text-[12px] text-text-secondary">
        {WEEK.map((w) => (
          <span key={w} className="py-2">
            {w}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {days.map((d) => {
          const k = ymd(d);
          const evs = byDay.get(k) ?? [];
          return (
            <div
              key={k}
              role="button"
              tabIndex={0}
              onClick={() => onDay(k)}
              onKeyDown={(e) => e.key === "Enter" && onDay(k)}
              className={cn("min-h-[104px] cursor-pointer border-r border-b border-neutral-100 p-1 last:border-r-0 hover:bg-neutral-50", d.getMonth() !== month && "bg-neutral-50/60 text-neutral-400", k === day && "ring-2 ring-inset ring-primary/40")}
            >
              <p className={cn("px-1 text-[12px] tabular-nums", k === today ? "font-bold text-primary" : "text-text-secondary")}>{d.getDate()}</p>
              {evs.slice(0, 4).map((ev) => (
                <Chip key={ev.id} ev={ev} onOpen={onOpen} />
              ))}
              {evs.length > 4 && <p className="px-1 text-[11px] text-text-secondary">+{evs.length - 4}</p>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DayList({ date, events, onOpen }: { date: string; events: MarketEventView[]; onOpen: (id: string) => void }) {
  const d = new Date(`${date}T00:00:00`);
  return (
    <section className="rounded-[20px] bg-white px-4 py-4">
      <p className="text-[14px] font-bold text-text-primary">
        {d.getMonth() + 1}월 {d.getDate()}일 ({WEEK[d.getDay()]})
      </p>
      {events.length === 0 && <p className="mt-2 text-[13px] text-text-secondary">일정이 없습니다.</p>}
      <div className="mt-1">
        {events.map((ev) => (
          <Row key={ev.id} ev={ev} onOpen={onOpen} compact />
        ))}
      </div>
    </section>
  );
}

function Row({ ev, onOpen, compact }: { ev: MarketEventView; onOpen: (id: string) => void; compact?: boolean }) {
  return (
    <button type="button" onClick={() => onOpen(ev.id)} className="flex w-full cursor-pointer items-start gap-2 border-b border-neutral-100 py-2 text-left last:border-0 hover:bg-neutral-50">
      <span className="w-11 shrink-0 text-[12px] text-text-secondary tabular-nums">{ev.kstTime || "종일"}</span>
      <span className="min-w-0 flex-1">
        <span className={cn("block truncate text-[13px]", ev.importance >= 3 ? "font-semibold text-text-primary" : "text-text-primary")}>
          {compact ? `${ev.countryKo} ${ev.short}` : ev.title}
          {ev.alerted && <BellRing className="ml-1 inline size-3" aria-label="알림 걸림" />}
        </span>
        <span className="block truncate text-[11px] text-text-secondary">
          {[ev.categoryKo, stars(ev.importance), ev.period, ev.localTime].filter(Boolean).join(" · ")}
          {ev.status === "released" && ` · 실제 ${ev.actualText || fmtValue(ev.actual, ev)}`}
        </span>
      </span>
    </button>
  );
}

function WeekCols({ start, byDay, onOpen }: { start: Date; byDay: Map<string, MarketEventView[]>; onOpen: (id: string) => void }) {
  return (
    <div className="grid grid-cols-7 gap-2">
      {Array.from({ length: 7 }, (_, i) => addDays(start, i)).map((d) => {
        const k = ymd(d);
        return (
          <section key={k} className="min-h-[280px] rounded-2xl bg-white px-2 py-2">
            <p className={cn("px-1 text-[12px] font-semibold", k === ymd(new Date()) ? "text-primary" : "text-text-secondary")}>
              {d.getMonth() + 1}/{d.getDate()} ({WEEK[d.getDay()]})
            </p>
            {(byDay.get(k) ?? []).map((ev) => (
              <Chip key={ev.id} ev={ev} onOpen={onOpen} />
            ))}
          </section>
        );
      })}
    </div>
  );
}

/** 일정표 — 시간(한국) · 국가 · 중요도 · 일정 · 실제 · 예상 · 이전 */
function Table({ events, onOpen }: { events: MarketEventView[]; onOpen: (id: string) => void }) {
  const groups = new Map<string, MarketEventView[]>();
  for (const ev of events) groups.set(ev.date, [...(groups.get(ev.date) ?? []), ev]);
  if (!events.length) return <p className="rounded-[20px] bg-white px-6 py-8 text-[13px] text-text-secondary">일정이 없습니다.</p>;
  return (
    <div className="overflow-hidden rounded-[20px] bg-white">
      <div className="grid grid-cols-[60px_56px_52px_minmax(0,1fr)_96px_96px_96px_36px] gap-2 border-b border-neutral-200 px-4 py-2 text-[12px] font-semibold text-neutral-500">
        <span>시간</span>
        <span>국가</span>
        <span>중요도</span>
        <span>일정</span>
        <span className="text-right">실제</span>
        <span className="text-right">예상</span>
        <span className="text-right">이전</span>
        <span />
      </div>
      {[...groups.entries()].map(([d, evs]) => {
        const dd = new Date(`${d}T00:00:00`);
        return (
          <div key={d}>
            <p className="bg-neutral-50 px-4 py-1.5 text-[12px] font-semibold text-text-secondary">
              {dd.getFullYear()}년 {dd.getMonth() + 1}월 {dd.getDate()}일 ({WEEK[dd.getDay()]})
            </p>
            {evs.map((ev) => (
              <button
                key={ev.id}
                type="button"
                onClick={() => onOpen(ev.id)}
                className="grid w-full cursor-pointer grid-cols-[60px_56px_52px_minmax(0,1fr)_96px_96px_96px_36px] items-center gap-2 border-b border-neutral-100 px-4 py-2 text-left text-[13px] last:border-0 hover:bg-neutral-50"
              >
                <span className="text-text-secondary tabular-nums">{ev.kstTime || "종일"}</span>
                <span>{ev.countryKo}</span>
                <span className="text-[11px] text-text-secondary">{stars(ev.importance)}</span>
                <span className={cn("truncate", ev.importance >= 3 && "font-semibold")}>
                  {ev.title}
                  {ev.period && <span className="font-normal text-text-secondary"> · {ev.period}</span>}
                </span>
                <span className="text-right font-semibold tabular-nums">{ev.category === "meeting" ? ev.actualText || (ev.actual != null ? fmtValue(ev.actual, ev) : "") : ev.actual != null ? fmtValue(ev.actual, ev) : ""}</span>
                <span className="text-right text-text-secondary tabular-nums">{ev.forecast != null ? fmtValue(ev.forecast, ev) : ""}</span>
                <span className="text-right text-text-secondary tabular-nums">{ev.previous != null ? fmtValue(ev.previous, ev) : ""}</span>
                <span className="flex justify-center">{ev.alerted && <BellRing className="size-3.5" aria-label="알림 걸림" />}</span>
              </button>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function AlertList({ alerts, onOpen, onDeleted }: { alerts: EventAlertView[] | null; onOpen: (id: string) => void; onDeleted: () => void }) {
  if (alerts === null) return <p className="text-[13px] text-text-secondary">불러오는 중…</p>;
  if (!alerts.length) return <p className="rounded-[20px] bg-white px-6 py-8 text-[13px] text-text-secondary">걸어 둔 알림이 없습니다. 일정을 눌러 [알림 받기]를 누르거나, 채팅에서 "다음 주 미국 CPI 발표되면 알려 줘"라고 하면 됩니다.</p>;
  const del = async (a: EventAlertView) => {
    try {
      await deleteEventAlert(a.id);
      onDeleted();
    } catch {
      toast.error("지우지 못했습니다.", { position: "top-center" });
    }
  };
  return (
    <div className="overflow-hidden rounded-[20px] bg-white">
      {alerts.map((a) => (
        <div key={a.id} className="flex items-center gap-3 border-b border-neutral-100 px-5 py-3 text-[13px] last:border-0">
          <Bell className="size-4 shrink-0 text-neutral-500" aria-hidden />
          <button type="button" disabled={!a.event} onClick={() => a.event && onOpen(a.event.id)} className="min-w-0 flex-1 cursor-pointer text-left enabled:hover:text-primary">
            <span className="block truncate font-semibold text-text-primary">{a.title}</span>
            <span className="block truncate text-[12px] text-text-secondary">
              {a.repeat ? "다음 발표마다" : a.event ? `${a.event.date} ${a.event.kstTime}${a.event.period ? ` · ${a.event.period}` : ""}` : ""}
              {" · "}
              {a.all ? "워크스페이스 전원" : "나"}
              {a.channels.workspace && " · 워크스페이스 메시지"}
              {a.channels.webhook && " · 웹훅"}
              {a.lastSentAt && ` · 보냄 ${new Date(a.lastSentAt).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}`}
              {!a.enabled && !a.repeat && " · 끝남"}
            </span>
          </button>
          <button type="button" aria-label="알림 지우기" title="알림 지우기" onClick={() => void del(a)} className="flex size-8 cursor-pointer items-center justify-center rounded-md text-text-secondary hover:bg-neutral-100">
            <Trash2 className="size-4" aria-hidden />
          </button>
        </div>
      ))}
    </div>
  );
}

function EventDrawer({ ev, keys, isAdmin, onClose, onChange, onAlerted }: { ev: MarketEventView; keys: KeyStatus | null; isAdmin: boolean; onClose: () => void; onChange: (e: MarketEventView) => void; onAlerted: () => void }) {
  const ws = useWorkspace();
  const canEdit = ws.can("editor");
  const [fc, setFc] = useState(ev.forecast != null ? String(ev.forecast) : "");
  const [toAll, setToAll] = useState(false);
  const [repeat, setRepeat] = useState(false);
  const [wsMsg, setWsMsg] = useState(false);
  const [hook, setHook] = useState(false);
  const [act, setAct] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const run = async (fn: () => Promise<unknown>, ok: string, fail: string) => {
    setBusy(true);
    try {
      await fn();
      toast.success(ok, { position: "top-center" });
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : fail, { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };
  const det = ev.detect;
  const val = (v: number | null) => (v == null ? "—" : fmtValue(v, ev));

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onMouseDown={onClose}>
      <aside onMouseDown={(e) => e.stopPropagation()} className="thin-scrollbar flex h-full w-full max-w-[440px] flex-col overflow-y-auto bg-white shadow-2xl">
        <header className="flex items-start gap-3 border-b border-neutral-200 px-5 py-4">
          <div className="min-w-0 flex-1">
            <p className="text-[12px] text-text-secondary">
              {ev.countryKo} · {ev.categoryKo} · {stars(ev.importance)}
            </p>
            <h2 className="text-[17px] font-bold text-text-primary">{ev.title}</h2>
            {ev.period && <p className="text-[13px] text-text-secondary">{ev.period}</p>}
          </div>
          <button type="button" aria-label="닫기" onClick={onClose} className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-text-secondary hover:bg-neutral-100">
            <X className="size-4" aria-hidden />
          </button>
        </header>
        <div className="flex flex-col gap-4 px-5 py-4 text-[13px]">
          <dl className="grid grid-cols-[64px_minmax(0,1fr)] gap-x-3 gap-y-1.5">
            <dt className="text-text-secondary">한국</dt>
            <dd className="tabular-nums">
              {ev.date} {ev.kstTime || "(시각 없음)"}
            </dd>
            {ev.localTime && (
              <>
                <dt className="text-text-secondary">현지</dt>
                <dd className="tabular-nums">{ev.localTime}</dd>
              </>
            )}
            {ev.agency && (
              <>
                <dt className="text-text-secondary">발표</dt>
                <dd>{ev.agency}</dd>
              </>
            )}
            <dt className="text-text-secondary">일정 출처</dt>
            <dd className="min-w-0">
              {ev.sourceUrl ? (
                <a href={ev.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 break-all hover:text-primary">
                  {ev.source === "fred" ? "FRED 발표일" : ev.source === "rule" ? "규칙" : "공식 일정표"}
                  <ExternalLink className="size-3" aria-hidden />
                </a>
              ) : (
                "—"
              )}
              {(ev.note || !ev.confirmed) && <span className="block text-[12px] text-text-secondary">{[!ev.confirmed && "공식 확인 전", ev.note].filter(Boolean).join(" · ")}</span>}
            </dd>
          </dl>

          {ev.category !== "holiday" && ev.category !== "issue" && (
            <div className="grid grid-cols-3 gap-2 rounded-xl bg-neutral-50 px-3 py-3 text-center">
              <div>
                <p className="text-[11px] text-text-secondary">실제</p>
                <p className="text-[16px] font-bold tabular-nums">{ev.category === "meeting" && ev.actualText ? ev.actualText : val(ev.actual)}</p>
              </div>
              <div>
                <p className="text-[11px] text-text-secondary">예상</p>
                <p className="text-[16px] tabular-nums">{val(ev.forecast)}</p>
              </div>
              <div>
                <p className="text-[11px] text-text-secondary">이전</p>
                <p className="text-[16px] tabular-nums">{val(ev.previous)}</p>
              </div>
            </div>
          )}

          {ev.indicatorId && (
            <p className="text-[12px] text-text-secondary">
              {ev.status === "released"
                ? `받음: ${det.via ?? ""}${det.lagSec != null ? ` · 예정 시각 ${det.lagSec}초 뒤` : det.backfill ? " · 지난 값 채움" : ""}`
                : ev.detectable
                  ? "발표 시각부터 공식 소스를 확인해 값이 나오면 바로 알립니다."
                  : "값 자동 감지 없음 — 일정만"}
              {det.url && (
                <a href={det.url} target="_blank" rel="noreferrer" className="ml-1 inline-flex items-center gap-0.5 hover:text-primary">
                  원문
                  <ExternalLink className="size-3" aria-hidden />
                </a>
              )}
            </p>
          )}

          {canEdit && ev.indicatorId && ev.category === "release" && ev.status !== "released" && (
            <div className="flex items-center gap-1.5">
              <span className="w-12 text-text-secondary">예상치</span>
              <input value={fc} inputMode="decimal" onChange={(e) => setFc(e.target.value)} placeholder="직접 넣기" className="h-8 w-28 rounded-md border border-neutral-200 px-2 tabular-nums" />
              <span className="text-text-secondary">{ev.unit}</span>
              <button
                type="button"
                disabled={busy || (fc !== "" && !Number.isFinite(Number(fc)))}
                onClick={() => void run(async () => onChange(await setForecast(ws.workspaceId, ev.id, fc === "" ? null : Number(fc))), "예상치를 저장했습니다.", "저장하지 못했습니다.")}
                className="h-8 cursor-pointer rounded-md border border-neutral-200 px-2.5 hover:bg-neutral-50 disabled:opacity-50"
              >
                저장
              </button>
            </div>
          )}

          <section className="rounded-xl border border-neutral-200 px-3 py-3">
            <p className="flex items-center gap-1.5 font-semibold text-text-primary">
              <Bell className="size-4" aria-hidden />
              {ev.alerted ? "알림이 걸려 있습니다" : "알림 받기"}
            </p>
            {!ev.alerted && ev.status !== "released" && (
              <>
                <div className="mt-2 flex flex-col gap-1.5">
                  <Check on={toAll} disabled={!canEdit} onChange={setToAll} label="워크스페이스 전원에게" />
                  {ev.indicatorId && <Check on={repeat} onChange={setRepeat} label="다음 발표마다(이 지표)" />}
                  <Check on={wsMsg} disabled={!canEdit} onChange={setWsMsg} label="워크스페이스 메시지로도" />
                  {keys?.webhook && <Check on={hook} onChange={setHook} label="웹훅으로도" />}
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(
                      async () => {
                        await createEventAlerts(ws.workspaceId, { eventIds: [ev.id], indicatorIds: repeat && ev.indicatorId ? [ev.indicatorId] : [], repeat, all: toAll, workspace: wsMsg, webhook: hook });
                        onAlerted();
                      },
                      "알림을 걸었습니다.",
                      "알림을 걸지 못했습니다.",
                    )
                  }
                  className="mt-3 h-9 w-full cursor-pointer rounded-lg bg-primary text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
                >
                  알림 받기
                </button>
              </>
            )}
            {ev.alerted && <p className="mt-1 text-[12px] text-text-secondary">'내 알림'에서 지울 수 있습니다.</p>}
          </section>

          {isAdmin && ev.indicatorId && (
            <div className="flex items-center gap-1.5 text-[12px]">
              <span className="text-text-secondary">실제치 넣기</span>
              <input value={act} inputMode="decimal" onChange={(e) => setAct(e.target.value)} className="h-7 w-24 rounded-md border border-neutral-200 px-2 tabular-nums" />
              <button
                type="button"
                disabled={busy || act === "" || !Number.isFinite(Number(act))}
                onClick={() => void run(async () => onChange(await putActual(ev.id, Number(act))), "넣었습니다. 걸린 알림을 보냈습니다.", "넣지 못했습니다.")}
                className="h-7 cursor-pointer rounded-md border border-neutral-200 px-2 hover:bg-neutral-50 disabled:opacity-50"
              >
                넣기
              </button>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function Check({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <label className={cn("flex items-center gap-2 text-[13px]", disabled ? "text-neutral-400" : "cursor-pointer text-text-primary")}>
      <input type="checkbox" checked={on} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="size-4 accent-primary" />
      {label}
    </label>
  );
}
