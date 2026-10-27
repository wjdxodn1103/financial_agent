"use client";

/** 할 일 보드·일정(달력·타임라인)이 같이 쓰는 조각 — 상태 표기, 담당자 동그라미, 작업 카드, 상세·새 작업 창, 칸 아래 빠른 추가. */
import { useState, type FormEvent, type ReactNode } from "react";
import { FileText, Plus, Trash2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useWorkspace } from "../../context";
import type { TaskStatus } from "../../hooks/useTasks";
import type { TaskItem } from "../../types";

/** bar = 일정 막대(달력·타임라인) */
export const STATUS: { id: TaskStatus; label: string; dot: string; col: string; pill: string; bar: string }[] = [
  { id: "todo", label: "작업 예정", dot: "bg-violet-500", col: "bg-violet-50/60", pill: "bg-violet-100 text-violet-800", bar: "bg-violet-100 text-violet-900 hover:bg-violet-200" },
  { id: "doing", label: "진행 중", dot: "bg-amber-500", col: "bg-amber-50/60", pill: "bg-amber-100 text-amber-800", bar: "bg-amber-100 text-amber-900 hover:bg-amber-200" },
  { id: "review", label: "검토 중", dot: "bg-primary", col: "bg-primary-soft/60", pill: "bg-primary-soft text-primary-soft-foreground", bar: "bg-blue-100 text-blue-900 hover:bg-blue-200" },
  { id: "done", label: "완료", dot: "bg-emerald-500", col: "bg-emerald-50/60", pill: "bg-emerald-100 text-emerald-800", bar: "bg-emerald-50 text-emerald-700/70 line-through hover:bg-emerald-100" },
];

const AVATAR = ["bg-sky-500", "bg-violet-500", "bg-emerald-500", "bg-amber-500", "bg-rose-500", "bg-teal-500"];

export function Avatar({ userId, size = 22 }: { userId: string | null; size?: number }) {
  const ws = useWorkspace();
  if (!userId) return null;
  const name = ws.nameOf(userId);
  const tone = AVATAR[[...userId].reduce((n, c) => n + c.charCodeAt(0), 0) % AVATAR.length];
  return (
    <span title={name} style={{ width: size, height: size, fontSize: size * 0.48 }} className={cn("inline-flex shrink-0 items-center justify-center rounded-full font-bold text-white", tone)}>
      {name.slice(0, 1)}
    </span>
  );
}

export const pad = (n: number) => String(n).padStart(2, "0");
export const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export function dueText(due: string): string {
  const [, m, d] = due.split("-").map(Number);
  return `${m}월 ${d}일`;
}

/** 기간 표기 — 하루짜리는 '10월 24일', 기간은 '10월 20일 – 24일'(달이 바뀌면 '10월 30일 – 11월 2일') */
export function rangeText(start: string, due: string): string {
  if (!start || start === due) return dueText(due);
  const [, sm] = start.split("-").map(Number);
  const [, em, ed] = due.split("-").map(Number);
  return `${dueText(start)} – ${sm === em ? `${ed}일` : dueText(due)}`;
}

/** 보드·일정의 카드 — 끌어서 옮기고 누르면 상세 */
export function TaskCard({ t, draggable, dragging, showDue = true, showStatus = false, onDragStart, onDragEnd, onOpen }: { t: TaskItem; draggable: boolean; dragging: boolean; showDue?: boolean; showStatus?: boolean; onDragStart: () => void; onDragEnd: () => void; onOpen: () => void }) {
  const today = ymd(new Date());
  const late = t.status !== "done" && t.due && t.due < today;
  const st = STATUS.find((s) => s.id === t.status);
  return (
    <div
      draggable={draggable}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", t.id);
        onDragStart();
      }}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      className={cn("cursor-pointer rounded-xl bg-white px-3.5 py-3 shadow-[0_1px_3px_rgba(0,27,55,0.08)] transition-shadow hover:shadow-[0_4px_12px_rgba(0,27,55,0.10)]", dragging && "opacity-40", draggable && "active:cursor-grabbing")}
    >
      <p className={cn("flex items-start gap-1.5 text-[14px] leading-5 font-medium", t.status === "done" ? "text-neutral-400 line-through" : "text-text-primary")}>
        {t.source.kind === "report" && <FileText className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />}
        {t.title}
      </p>
      {(t.assigneeId || (showDue && t.due) || showStatus) && (
        <div className="mt-2 flex items-center gap-1.5">
          <Avatar userId={t.assigneeId} size={20} />
          {showStatus && st && <span className={cn("rounded-md px-1.5 py-0.5 text-[11px] font-semibold", st.pill)}>{st.label}</span>}
          {showDue && t.due && <span className={cn("ml-auto text-[12px] font-medium", late ? "text-[#f04452]" : "text-neutral-500")}>{rangeText(t.start, t.due)}</span>}
        </div>
      )}
    </div>
  );
}

/** 칸 아래 빠른 추가 — 누르면 입력 줄이 열리고 Enter 로 만든다 */
export function InlineAdd({ onAdd, label = "새 항목" }: { onAdd: (title: string) => Promise<unknown>; label?: string }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    await onAdd(title.trim());
    setTitle("");
  };
  if (!open)
    return (
      <button type="button" onClick={() => setOpen(true)} className="flex w-full cursor-pointer items-center gap-1.5 rounded-xl px-3 py-2 text-[13px] font-medium text-neutral-500 transition-colors hover:bg-white/70 hover:text-neutral-700">
        <Plus className="size-4" aria-hidden />
        {label}
      </button>
    );
  return (
    <form onSubmit={(e) => void submit(e)} className="rounded-xl bg-white p-2 shadow-[0_1px_3px_rgba(0,27,55,0.08)]">
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        onBlur={() => !title.trim() && setOpen(false)}
        placeholder="제목"
        className="w-full rounded-lg px-2 py-1.5 text-[14px] outline-none"
      />
    </form>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[72px_1fr] items-center gap-3">
      <span className="text-[13px] font-medium text-neutral-500">{label}</span>
      {children}
    </div>
  );
}

export type TaskBody = { title?: string; detail?: string; assigneeId?: string | null; due?: string; start?: string; status?: TaskStatus };

/** 새 작업 창에 넘길 빈 항목 */
export function draftTask(patch: Partial<TaskItem> = {}): TaskItem {
  return { id: "", title: "", detail: "", assigneeId: null, due: "", start: "", status: "todo", source: { kind: "manual" }, createdBy: "", createdAt: "", updatedAt: "", ...patch };
}

/** 작업 상세 — 제목·상태·담당·기간·메모, 지우기. t.id 가 비어 있으면 새 작업 만들기 */
export function TaskDialog({ t, canEdit, canMove, onClose, onSave, onRemove, onOpenReport }: { t: TaskItem; canEdit: boolean; canMove: boolean; onClose: () => void; onSave: (body: TaskBody) => Promise<unknown>; onRemove?: () => Promise<unknown>; onOpenReport: (id: string) => void }) {
  const ws = useWorkspace();
  const editor = ws.can("editor");
  const isNew = !t.id;
  const [title, setTitle] = useState(t.title);
  const [status, setStatus] = useState<TaskStatus>(t.status);
  const [assignee, setAssignee] = useState(t.assigneeId ?? "");
  const [start, setStart] = useState(t.start || t.due);
  const [due, setDue] = useState(t.due);
  const [detail, setDetail] = useState(t.detail);
  const [busy, setBusy] = useState(false);
  const members = ws.detail?.members ?? [];
  const save = async () => {
    if (isNew && !title.trim()) return;
    setBusy(true);
    const end = due || start;
    await onSave({ title: title.trim() || t.title, status, due: end, start: start && start !== end ? start : "", ...(editor ? { assigneeId: assignee || null, detail } : {}) });
    setBusy(false);
    onClose();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="w-full max-w-[520px] rounded-[24px] bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <input
            value={title}
            autoFocus={isNew}
            disabled={!canEdit}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && void save()}
            placeholder={isNew ? "새 작업" : undefined}
            className="min-w-0 flex-1 rounded-lg text-[20px] font-bold text-text-primary outline-none placeholder:text-neutral-300 disabled:bg-transparent"
            aria-label="제목"
          />
          <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        <div className="mt-5 flex flex-col gap-3.5">
          <Field label="상태">
            <div className="flex flex-wrap gap-1.5">
              {STATUS.map((s) => (
                <button key={s.id} type="button" disabled={!canMove} onClick={() => setStatus(s.id)} className={cn("cursor-pointer rounded-lg px-2.5 py-1 text-[13px] font-semibold transition-colors disabled:cursor-default", status === s.id ? s.pill : "bg-neutral-100 text-neutral-500 hover:bg-neutral-200")}>
                  {s.label}
                </button>
              ))}
            </div>
          </Field>
          <Field label="담당">
            {editor ? (
              <select value={assignee} onChange={(e) => setAssignee(e.target.value)} className="h-9 rounded-lg bg-neutral-100 px-3 text-[14px] outline-none">
                <option value="">없음</option>
                {members.map((m) => (
                  <option key={m.user.id} value={m.user.id}>
                    {m.user.name} {m.user.title}
                  </option>
                ))}
              </select>
            ) : (
              <span className="flex items-center gap-2 text-[14px] text-text-primary">
                <Avatar userId={t.assigneeId} />
                {t.assigneeId ? ws.nameOf(t.assigneeId) : "없음"}
              </span>
            )}
          </Field>
          <Field label="기간">
            <div className="flex items-center gap-2">
              <input type="date" value={start} disabled={!canEdit} aria-label="시작" onChange={(e) => (setStart(e.target.value), (!due || e.target.value > due) && setDue(e.target.value))} className="h-9 w-fit rounded-lg bg-neutral-100 px-3 text-[14px] outline-none disabled:opacity-60" />
              <span className="text-neutral-400">–</span>
              <input type="date" value={due} disabled={!canEdit} aria-label="마감" onChange={(e) => (setDue(e.target.value), (!start || e.target.value < start) && setStart(e.target.value))} className="h-9 w-fit rounded-lg bg-neutral-100 px-3 text-[14px] outline-none disabled:opacity-60" />
            </div>
          </Field>
          {t.source.kind === "report" && t.source.reportId && (
            <Field label="문서">
              <button type="button" onClick={() => onOpenReport(t.source.reportId!)} className="flex w-fit cursor-pointer items-center gap-1.5 text-[14px] font-medium text-primary hover:underline">
                <FileText className="size-4" aria-hidden />
                문서 열기
              </button>
            </Field>
          )}
          <textarea value={detail} disabled={!editor} onChange={(e) => setDetail(e.target.value)} rows={4} placeholder="메모" className="mt-1 w-full resize-none rounded-xl bg-neutral-100 px-3.5 py-2.5 text-[14px] leading-6 outline-none disabled:opacity-70" />
        </div>
        <div className="mt-5 flex items-center justify-between">
          {canEdit && !isNew && onRemove ? (
            <button type="button" onClick={() => window.confirm("이 항목을 지울까요?") && void onRemove().then(onClose)} className="flex cursor-pointer items-center gap-1 rounded-lg px-2 py-1.5 text-[13px] font-medium text-neutral-500 hover:bg-neutral-100 hover:text-[#f04452]">
              <Trash2 className="size-4" aria-hidden />
              지우기
            </button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="h-10 cursor-pointer rounded-xl bg-neutral-100 px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-200">
              닫기
            </button>
            <button type="button" disabled={busy || (isNew && !title.trim())} onClick={() => void save()} className="h-10 cursor-pointer rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
              {isNew ? "만들기" : "저장"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
