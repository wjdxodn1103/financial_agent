"use client";

/**
 * 마이페이지(워크스페이스 홈) — 나의 업무를 한눈에(BE mypage.py): 요약 숫자, 할 일, 이번 주 일정, 검토 요청, 내 문서, 내가 한 일.
 * 보기 전용 — 등록·상태 바꾸기·요청 보내기는 하위 화면(할 일·일정·검토 요청·문서 작성)에서 한다. 카드의 '전체'가 그 화면으로 간다.
 * 토스 톤: 회색 바탕 위 흰 카드, 큰 숫자, 테두리 대신 면. 설명 문구는 두지 않는다.
 */
import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import { Check, ChevronLeft, ChevronRight, ClipboardCheck, FilePlus2, FileText, PenLine, Send, Upload } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { getMyPage } from "../../api";
import { useWorkspace } from "../../context";
import type { MyActivity, MyDocument, MyPage as MyPageData, MyReviewRequest, MyTodo } from "../../types";
import { NewDocumentDialog } from "../NewDocumentDialog";
import { STATUS } from "./taskParts";

const pad = (n: number) => String(n).padStart(2, "0");
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];

function parseYmd(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

function addDays(d: Date, n: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

function mondayOf(d: Date): Date {
  return addDays(new Date(d.getFullYear(), d.getMonth(), d.getDate()), -((d.getDay() + 6) % 7));
}

function dayLabel(s: string): string {
  const d = parseYmd(s);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${WEEKDAY[d.getDay()]})`;
}

function dueLabel(due: string, today: string): string {
  if (due === today) return "오늘";
  if (due === ymd(addDays(parseYmd(today), 1))) return "내일";
  return dayLabel(due);
}

function ago(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const min = Math.round((Date.now() - t) / 60000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  if (min < 60 * 24) return `${Math.round(min / 60)}시간 전`;
  const d = new Date(t);
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}

function Card({ title, count, onAll, right, children, className }: { title: string; count?: number; onAll?: () => void; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-[24px] bg-white px-6 py-5", className)}>
      <div className="flex min-h-8 items-center justify-between gap-3">
        <h2 className="flex items-center gap-1.5 text-[19px] font-bold tracking-tight text-text-primary">
          {title}
          {count !== undefined && count > 0 && <span className="text-[19px] font-bold text-primary">{count}</span>}
        </h2>
        <div className="flex items-center gap-2">
          {right}
          {onAll && (
            <button type="button" onClick={onAll} className="flex cursor-pointer items-center text-[14px] font-medium text-neutral-500 hover:text-neutral-700">
              전체
              <ChevronRight className="size-4" aria-hidden />
            </button>
          )}
        </div>
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Stat({ label, value, tone, onClick }: { label: string; value: number; tone?: "accent" | "danger"; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="cursor-pointer rounded-[20px] bg-white px-5 py-4 text-left transition-colors hover:bg-neutral-50">
      <span className="block text-[14px] font-medium text-neutral-600">{label}</span>
      <span className={cn("num mt-1 block text-[28px] leading-tight font-bold", value && tone === "danger" ? "text-[#f04452]" : value && tone === "accent" ? "text-primary" : "text-text-primary")}>
        {value}
        <span className="ml-0.5 text-[18px] font-semibold">건</span>
      </span>
    </button>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="py-8 text-center text-[15px] text-neutral-500">{children}</p>;
}

export function MyPage() {
  const ws = useWorkspace();
  const [page, setPage] = useState<MyPageData | null>(null);
  const [newDoc, setNewDoc] = useState(false);
  const today = ymd(new Date());

  useEffect(() => {
    let cancelled = false;
    getMyPage(ws.workspaceId)
      .then((p) => !cancelled && setPage(p))
      .catch(() => !cancelled && toast.error("불러오지 못했습니다.", { position: "top-center" }));
    return () => {
      cancelled = true;
    };
  }, [ws.workspaceId]);

  const open = (page?.todos ?? []).filter((t) => !t.done);
  const overdue = open.filter((t) => t.due && t.due < today);
  const dueToday = open.filter((t) => t.due === today);
  const waiting = (page?.received ?? []).filter((r) => !r.done);
  const drafting = (page?.documents ?? []).filter((d) => d.written < d.sections);

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
      <div className="mx-auto max-w-[1120px] px-8 pt-8 pb-14">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-[15px] font-medium text-neutral-500">{new Date().toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "long" })}</p>
            <h1 className="mt-1 text-[26px] leading-tight font-bold tracking-tight text-text-primary">{ws.me.name}님, 안녕하세요</h1>
          </div>
          <div className="flex items-center gap-2">
            {ws.can("editor") && (
              <button type="button" onClick={() => setNewDoc(true)} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover">
                <FilePlus2 className="size-4" aria-hidden />새 문서
              </button>
            )}
            <button type="button" onClick={() => ws.nav.view("documents")} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-white px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-50">
              <Upload className="size-4" aria-hidden />
              드라이브
            </button>
            <button type="button" onClick={() => ws.nav.view("reviews")} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-white px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-50">
              <ClipboardCheck className="size-4" aria-hidden />
              검수하기
            </button>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="오늘 할 일" value={dueToday.length} tone="accent" onClick={() => ws.nav.view("tasks")} />
          <Stat label="기한 지난 일" value={overdue.length} tone="danger" onClick={() => ws.nav.view("tasks")} />
          <Stat label="검토할 문서" value={waiting.length} tone="accent" onClick={() => ws.nav.view("requests")} />
          <Stat label="작성 중 문서" value={drafting.length} onClick={() => ws.nav.openReport(null)} />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
          <Todos todos={page?.todos ?? []} today={today} loading={!page} onAll={() => ws.nav.view("tasks")} />
          <Week todos={page?.todos ?? []} today={today} onAll={() => ws.nav.view("schedule")} />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Reviews received={page?.received ?? []} sent={page?.sent ?? []} onOpen={(id) => ws.nav.openReport(id)} onAll={() => ws.nav.view("requests")} />
          <Documents docs={page?.documents ?? []} onOpen={(id) => ws.nav.openReport(id)} onAll={() => ws.nav.openReport(null)} />
        </div>

        <Activity items={page?.activity ?? []} onOpen={(id) => ws.nav.openReport(id)} />
      </div>
      {newDoc && <NewDocumentDialog onClose={() => setNewDoc(false)} />}
    </div>
  );
}

function Todos({ todos, today, loading, onAll }: { todos: MyTodo[]; today: string; loading: boolean; onAll: () => void }) {
  const sunday = ymd(addDays(mondayOf(parseYmd(today)), 6));
  const open = todos.filter((t) => !t.done).sort((a, b) => (a.due || "9999").localeCompare(b.due || "9999"));
  const groups: { label: string; danger?: boolean; items: MyTodo[] }[] = [
    { label: "기한 지남", danger: true, items: open.filter((t) => t.due && t.due < today) },
    { label: "오늘", items: open.filter((t) => t.due === today) },
    { label: "이번 주", items: open.filter((t) => t.due > today && t.due <= sunday) },
    { label: "나중에", items: open.filter((t) => t.due > sunday) },
    { label: "날짜 없음", items: open.filter((t) => !t.due) },
  ].filter((g) => g.items.length);
  let left = 7;
  return (
    <Card title="할 일" count={open.length} onAll={onAll}>
      {!loading && !open.length && <Empty>할 일이 없어요</Empty>}
      {groups.map((g) => {
        if (left <= 0) return null;
        const items = g.items.slice(0, left);
        left -= items.length;
        return (
          <div key={g.label} className="mt-2 first:mt-0">
            <p className={cn("px-2 text-[13px] font-semibold", g.danger ? "text-[#f04452]" : "text-neutral-500")}>{g.label}</p>
            {items.map((t) => {
              const st = STATUS.find((s) => s.id === t.status);
              return (
                <button key={t.id} type="button" onClick={onAll} className="flex h-11 w-full cursor-pointer items-center gap-3 rounded-xl px-2 text-left transition-colors hover:bg-neutral-50">
                  <span className={cn("size-2 shrink-0 rounded-full", st?.dot ?? "bg-neutral-300")} aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-[15px] text-text-primary">{t.title}</span>
                  {st && t.status !== "todo" && <span className={cn("shrink-0 rounded-md px-1.5 py-0.5 text-[11px] font-semibold", st.pill)}>{st.label}</span>}
                  {t.due && <span className={cn("shrink-0 text-[13px] font-medium", t.due < today ? "text-[#f04452]" : "text-neutral-500")}>{dueLabel(t.due, today)}</span>}
                </button>
              );
            })}
          </div>
        );
      })}
      {open.length > 7 && <p className="mt-1 px-2 text-[13px] text-neutral-500">외 {open.length - 7}건</p>}
    </Card>
  );
}

function Week({ todos, today, onAll }: { todos: MyTodo[]; today: string; onAll: () => void }) {
  const [start, setStart] = useState(() => mondayOf(new Date()));
  const [date, setDate] = useState(today);
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => ymd(addDays(start, i))), [start]);
  /** 그날 걸쳐 있는 할 일(기간 시작~마감 안) */
  const on = (d: string) => todos.filter((t) => t.due && (t.start || t.due) <= d && d <= t.due);
  const items = on(date);

  return (
    <Card
      title="일정"
      onAll={onAll}
      right={
        <div className="flex items-center text-neutral-600">
          <button type="button" aria-label="지난 주" onClick={() => setStart((s) => addDays(s, -7))} className="cursor-pointer rounded-lg p-1 hover:bg-neutral-100">
            <ChevronLeft className="size-4" aria-hidden />
          </button>
          <button type="button" aria-label="다음 주" onClick={() => setStart((s) => addDays(s, 7))} className="cursor-pointer rounded-lg p-1 hover:bg-neutral-100">
            <ChevronRight className="size-4" aria-hidden />
          </button>
        </div>
      }
    >
      <div className="grid grid-cols-7 gap-1">
        {days.map((d) => {
          const dt = parseYmd(d);
          const openItems = on(d).filter((t) => !t.done);
          return (
            <button key={d} type="button" onClick={() => setDate(d)} className={cn("flex cursor-pointer flex-col items-center gap-1 rounded-2xl py-2 transition-colors", d === date ? "bg-primary-soft" : "hover:bg-neutral-50")}>
              <span className={cn("text-[12px] font-medium", dt.getDay() === 0 ? "text-[#f04452]" : "text-neutral-500")}>{WEEKDAY[dt.getDay()]}</span>
              <span className={cn("num flex size-9 items-center justify-center rounded-full text-[16px] font-bold", d === today ? "bg-primary text-white" : "text-text-primary")}>{dt.getDate()}</span>
              <span className={cn("size-1.5 rounded-full", openItems.length ? (d < today ? "bg-[#f04452]" : "bg-primary") : "bg-transparent")} aria-hidden />
            </button>
          );
        })}
      </div>
      <div className="mt-4 rounded-2xl bg-neutral-50 px-4 py-3">
        <p className="text-[14px] font-semibold text-text-primary">{dayLabel(date)}</p>
        {items.length === 0 ? (
          <p className="mt-2 text-[14px] text-neutral-500">일정이 없어요</p>
        ) : (
          <ul className="mt-2 flex flex-col gap-1.5">
            {items.map((t) => (
              <li key={t.id} className="flex items-center gap-2 text-[14px]">
                <span className={cn("size-2 shrink-0 rounded-full", t.done ? "bg-neutral-300" : "bg-primary")} aria-hidden />
                <span className={cn("truncate", t.done ? "text-neutral-400 line-through" : "text-text-primary")}>{t.title}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

function Reviews({ received, sent, onOpen, onAll }: { received: MyReviewRequest[]; sent: MyReviewRequest[]; onOpen: (reportId: string) => void; onAll: () => void }) {
  const [picked, setTab] = useState<"in" | "out" | null>(null);
  // 고르기 전에는 내용이 있는 쪽(받은 요청 우선)
  const tab = picked ?? (received.length || !sent.length ? "in" : "out");
  const list = (tab === "in" ? received : sent)
    .slice()
    .sort((a, b) => Number(a.done) - Number(b.done) || b.at.localeCompare(a.at))
    .slice(0, 5);
  const waiting = received.filter((r) => !r.done).length;
  return (
    <Card
      title="검토 요청"
      count={waiting}
      onAll={onAll}
      right={
        <div className="flex rounded-xl bg-neutral-100 p-1 text-[13px] font-semibold">
          {(
            [
              ["in", `받은 ${received.length}`],
              ["out", `보낸 ${sent.length}`],
            ] as const
          ).map(([id, label]) => (
            <button key={id} type="button" onClick={() => setTab(id)} className={cn("cursor-pointer rounded-lg px-3 py-1 transition-colors", tab === id ? "bg-white text-text-primary shadow-sm" : "text-neutral-500 hover:text-neutral-700")}>
              {label}
            </button>
          ))}
        </div>
      }
    >
      {list.length === 0 && <Empty>{tab === "in" ? "받은 요청이 없어요" : "보낸 요청이 없어요"}</Empty>}
      {list.map((r) => (
        <button key={r.taskId} type="button" onClick={() => onOpen(r.reportId)} className="flex w-full cursor-pointer items-center gap-3 rounded-xl px-2 py-2.5 text-left transition-colors hover:bg-neutral-50">
          <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-full", r.done ? "bg-neutral-100 text-neutral-400" : "bg-primary-soft text-primary")}>
            <FileText className="size-[18px]" aria-hidden />
          </span>
          <span className="min-w-0 flex-1">
            <span className={cn("block truncate text-[15px] font-medium", r.done ? "text-neutral-500" : "text-text-primary")}>{r.title}</span>
            <span className="block truncate text-[13px] text-neutral-500">
              {r.person} · {ago(r.at)}
            </span>
          </span>
          <span className={cn("shrink-0 rounded-lg px-2.5 py-1 text-[12px] font-semibold", r.done ? "bg-neutral-100 text-neutral-500" : "bg-primary-soft text-primary")}>{r.done ? "완료" : tab === "in" ? "검토 대기" : "검토 중"}</span>
        </button>
      ))}
    </Card>
  );
}

function Documents({ docs, onOpen, onAll }: { docs: MyDocument[]; onOpen: (id: string) => void; onAll: () => void }) {
  const ws = useWorkspace();
  const typeTitle = (id: string) => ws.meta.reportTypes.find((t) => t.id === id)?.title ?? "";
  return (
    <Card title="내 문서" count={docs.length} onAll={onAll}>
      {docs.length === 0 && <Empty>아직 만든 문서가 없어요</Empty>}
      {docs.slice(0, 5).map((d) => {
        const pct = d.sections ? Math.round((d.written / d.sections) * 100) : 0;
        return (
          <button key={d.id} type="button" onClick={() => onOpen(d.id)} className="block w-full cursor-pointer rounded-xl px-2 py-2.5 text-left transition-colors hover:bg-neutral-50">
            <span className="flex items-center gap-3">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[15px] font-medium text-text-primary">{d.title}</span>
                <span className="block truncate text-[13px] text-neutral-500">{[typeTitle(d.reportType), ago(d.updatedAt)].filter(Boolean).join(" · ")}</span>
              </span>
              {d.review && (
                <span className={cn("shrink-0 rounded-lg px-2.5 py-1 text-[12px] font-semibold", d.review.done ? "bg-neutral-100 text-neutral-500" : "bg-primary-soft text-primary")}>
                  {d.review.person.split(" ")[0]} {d.review.done ? "검토 완료" : "검토 중"}
                </span>
              )}
            </span>
            <span className="mt-2 flex items-center gap-2">
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-neutral-100">
                <span className="block h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
              </span>
              <span className="num shrink-0 text-[12px] font-semibold text-neutral-500">
                {d.written}/{d.sections}
              </span>
            </span>
          </button>
        );
      })}
    </Card>
  );
}

const ACT: Record<MyActivity["kind"], { icon: ComponentType<{ className?: string }>; tone: string; verb: string }> = {
  write: { icon: PenLine, tone: "bg-primary-soft text-primary", verb: "작성" },
  upload: { icon: Upload, tone: "bg-emerald-50 text-emerald-600", verb: "업로드" },
  review: { icon: ClipboardCheck, tone: "bg-orange-50 text-orange-600", verb: "검수" },
  request: { icon: Send, tone: "bg-violet-50 text-violet-600", verb: "검토 요청" },
  done: { icon: Check, tone: "bg-neutral-100 text-neutral-500", verb: "완료" },
};

function Activity({ items, onOpen }: { items: MyActivity[]; onOpen: (reportId: string) => void }) {
  const [more, setMore] = useState(false);
  const shown = more ? items : items.slice(0, 6);
  return (
    <Card
      title="내가 한 일"
      className="mt-4"
      right={
        items.length > 6 && (
          <button type="button" onClick={() => setMore((v) => !v)} className="cursor-pointer text-[14px] font-medium text-neutral-500 hover:text-neutral-700">
            {more ? "접기" : "더 보기"}
          </button>
        )
      }
    >
      {items.length === 0 && <Empty>아직 기록이 없어요</Empty>}
      <div className="grid gap-x-6 md:grid-cols-2">
        {shown.map((a, i) => {
          const k = ACT[a.kind];
          const Icon = k.icon;
          const body = (
            <>
              <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-full", k.tone)}>
                <Icon className="size-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[15px] text-text-primary">{a.title}</span>
                <span className="block truncate text-[13px] text-neutral-500">
                  {k.verb}
                  {a.person ? ` · ${a.person}` : ""}
                </span>
              </span>
              <span className="shrink-0 text-[13px] text-neutral-500">{ago(a.at)}</span>
            </>
          );
          return a.reportId ? (
            <button key={i} type="button" onClick={() => onOpen(a.reportId!)} className="flex w-full cursor-pointer items-center gap-3 rounded-xl px-2 py-2.5 text-left transition-colors hover:bg-neutral-50">
              {body}
            </button>
          ) : (
            <div key={i} className="flex items-center gap-3 rounded-xl px-2 py-2.5">
              {body}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
