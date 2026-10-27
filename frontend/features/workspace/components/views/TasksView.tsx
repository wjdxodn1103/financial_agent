"use client";

/**
 * 할 일 — 상태별 칸반(작업 예정 · 진행 중 · 검토 중 · 완료). 끌어 옮기면 상태가 바뀌고, 카드를 누르면 상세(담당 배정·날짜·메모).
 * 보기: 전체 작업 / 내 작업. 칸 아래 '새 항목'은 그 상태로 바로 만든다. 업무 배정(담당 지정)은 편집자 이상.
 */
import { useMemo, useState } from "react";
import { ListTodo, Plus, User, Users } from "lucide-react";

import { cn } from "@/lib/utils";
import { useWorkspace } from "../../context";
import { useTasks, type TaskStatus } from "../../hooks/useTasks";
import type { TaskItem } from "../../types";
import { InlineAdd, STATUS, TaskCard, TaskDialog } from "./taskParts";

export function TasksView() {
  const ws = useWorkspace();
  const t = useTasks();
  const [view, setView] = useState<"all" | "mine">("all");
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<TaskStatus | null>(null);
  const [open, setOpen] = useState<TaskItem | null>(null);
  const shown = useMemo(() => t.tasks.filter((x) => view === "all" || x.assigneeId === ws.me.id), [t.tasks, view, ws.me.id]);

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-auto bg-white">
      <div className="px-8 pt-8 pb-10">
        <h1 className="flex items-center gap-2.5 text-[26px] leading-tight font-bold tracking-tight text-text-primary">
          <ListTodo className="size-7 text-primary" aria-hidden />할 일
        </h1>
        <div className="mt-5 flex items-center justify-between gap-3 border-b border-neutral-100 pb-2">
          <div className="flex items-center gap-1">
            {(
              [
                ["all", "전체 작업", Users],
                ["mine", "내 작업", User],
              ] as const
            ).map(([id, label, Icon]) => (
              <button key={id} type="button" onClick={() => setView(id)} className={cn("flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1.5 text-[14px] font-medium transition-colors", view === id ? "bg-neutral-100 text-text-primary" : "text-neutral-500 hover:bg-neutral-50")}>
                <Icon className="size-4" aria-hidden />
                {label}
              </button>
            ))}
          </div>
          <NewTaskButton onCreate={(title) => t.create(title, { status: "todo" })} />
        </div>

        <div className="mt-4 grid min-w-[880px] grid-cols-4 gap-3">
          {STATUS.map((col) => {
            const items = shown.filter((x) => x.status === col.id).sort((a, b) => (a.due || "9999").localeCompare(b.due || "9999"));
            return (
              <div
                key={col.id}
                onDragOver={(e) => {
                  if (!dragging) return;
                  e.preventDefault();
                  setOver(col.id);
                }}
                onDragLeave={() => setOver((c) => (c === col.id ? null : c))}
                onDrop={(e) => {
                  e.preventDefault();
                  const task = t.tasks.find((x) => x.id === dragging);
                  setDragging(null);
                  setOver(null);
                  if (task && task.status !== col.id) void t.setStatus(task, col.id);
                }}
                className={cn("flex min-h-[320px] flex-col gap-2 rounded-2xl p-2.5 transition-shadow", col.col, over === col.id && "ring-2 ring-primary/40")}
              >
                <p className="flex items-center gap-2 px-1.5 pt-0.5 pb-1">
                  <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[13px] font-semibold", col.pill)}>
                    <span className={cn("size-2 rounded-full", col.dot)} aria-hidden />
                    {col.label}
                  </span>
                  <span className="text-[13px] font-semibold text-neutral-500">{items.length}</span>
                </p>
                {items.map((x) => (
                  <TaskCard key={x.id} t={x} draggable={t.canMove(x)} dragging={dragging === x.id} onDragStart={() => setDragging(x.id)} onDragEnd={() => (setDragging(null), setOver(null))} onOpen={() => setOpen(x)} />
                ))}
                <InlineAdd onAdd={(title) => t.create(title, { status: col.id })} />
              </div>
            );
          })}
        </div>
        {t.loading && <p className="mt-4 text-[14px] text-neutral-500">불러오는 중…</p>}
      </div>
      {open && (
        <TaskDialog
          t={open}
          canEdit={t.canEdit(open)}
          canMove={t.canMove(open)}
          onClose={() => setOpen(null)}
          onSave={(body) => t.save(open, body)}
          onRemove={() => t.remove(open)}
          onOpenReport={(id) => ws.nav.openReport(id)}
        />
      )}
    </div>
  );
}

function NewTaskButton({ onCreate }: { onCreate: (title: string) => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  if (!open)
    return (
      <button type="button" onClick={() => setOpen(true)} className="flex h-9 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-3.5 text-[14px] font-semibold text-white hover:bg-primary-hover">
        <Plus className="size-4" aria-hidden />새 항목
      </button>
    );
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!title.trim()) return;
        void onCreate(title.trim()).then(() => {
          setTitle("");
          setOpen(false);
        });
      }}
      className="flex items-center gap-1.5"
    >
      <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setOpen(false)} placeholder="제목" className="h-9 w-56 rounded-xl bg-neutral-100 px-3 text-[14px] outline-none focus:bg-white focus:ring-2 focus:ring-primary/30" />
      <button type="submit" disabled={!title.trim()} className="h-9 cursor-pointer rounded-xl bg-primary px-3.5 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40">
        추가
      </button>
    </form>
  );
}
