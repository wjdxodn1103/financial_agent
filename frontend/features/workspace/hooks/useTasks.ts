"use client";

/**
 * 할 일·일정 화면이 같이 쓰는 작업 항목 상태 — 목록·만들기·상태/기간/담당 바꾸기·지우기.
 * 기간 = start~due(시작이 없으면 마감 하루짜리).
 * 권한 차이를 여기서 흡수한다: 편집자 이상은 작업 항목 API(담당 배정 포함), 그 밖의 멤버는 마이페이지 API(자기 할 일만).
 * 화면에 보이는 것 = 직접 만든 작업(manual)과 리포트 검토 요청(report). 검수 지적·기록 비서에서 온 것은 숨긴 기능이라 뺀다.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ApiError } from "../../report/api";
import { addMyTodo, createTask, deleteMyTodo, deleteTask, listTasks, updateMyTask, updateTask } from "../api";
import { useWorkspace } from "../context";
import type { TaskItem } from "../types";

export type TaskStatus = TaskItem["status"];

const SHOWN = new Set(["manual", "report"]);

export function useTasks() {
  const ws = useWorkspace();
  const editor = ws.can("editor");
  const [all, setAll] = useState<TaskItem[] | null>(null);

  const load = useCallback(async () => {
    try {
      setAll(await listTasks(ws.workspaceId));
    } catch {
      setAll([]);
    }
  }, [ws.workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const tasks = useMemo(() => (all ?? []).filter((t) => SHOWN.has(t.source.kind ?? "manual")), [all]);

  const run = useCallback(
    async (fn: () => Promise<unknown>, fail = "저장하지 못했습니다.") => {
      try {
        await fn();
      } catch (e) {
        toast.error(e instanceof ApiError && e.status < 500 ? e.message : fail, { position: "top-center" });
      }
      await load();
    },
    [load],
  );

  const patchLocal = (id: string, patch: Partial<TaskItem>) => setAll((cur) => (cur ?? []).map((t) => (t.id === id ? { ...t, ...patch } : t)));
  const mine = (t: TaskItem) => t.assigneeId === ws.me.id;
  const canMove = (t: TaskItem) => editor || (mine(t) && ws.can("reviewer"));
  const canEdit = (t: TaskItem) => editor || (mine(t) && (t.source.kind ?? "manual") === "manual");

  return {
    tasks,
    loading: all === null,
    editor,
    canMove,
    canEdit,
    reload: load,
    create: (title: string, opts: { status?: TaskStatus; due?: string; start?: string; assigneeId?: string | null; detail?: string } = {}) =>
      run(async () => {
        if (editor) {
          const before = new Set((all ?? []).map((t) => t.id));
          const res = await createTask(ws.workspaceId, { title, due: opts.due ?? "", start: opts.start ?? "", assigneeId: opts.assigneeId === undefined ? ws.me.id : opts.assigneeId, detail: opts.detail ?? "" });
          const made = res.tasks.find((t) => !before.has(t.id));
          if (made && opts.status && opts.status !== "todo") await updateTask(ws.workspaceId, made.id, { status: opts.status });
        } else {
          const res = await addMyTodo(ws.workspaceId, title, opts.due ?? "", opts.start ?? "");
          const made = res.todos.find((t) => t.title === title && t.status === "todo" && !(all ?? []).some((x) => x.id === t.id));
          if (made && opts.status && opts.status !== "todo") await updateTask(ws.workspaceId, made.id, { status: opts.status });
        }
      }, "만들지 못했습니다."),
    setStatus: (t: TaskItem, status: TaskStatus) => {
      patchLocal(t.id, { status });
      return run(() => updateTask(ws.workspaceId, t.id, { status }));
    },
    /** 기간 바꾸기(끌어 옮기기·늘이기) — 시작이 마감과 같으면 하루짜리 */
    setDates: (t: TaskItem, start: string, due: string) => {
      const s = start === due ? "" : start;
      patchLocal(t.id, { start: s, due });
      return run(() => (editor ? updateTask(ws.workspaceId, t.id, { start: s, due }) : updateMyTask(ws.workspaceId, t.id, { start: s, due })));
    },
    save: (t: TaskItem, body: { title?: string; detail?: string; assigneeId?: string | null; due?: string; start?: string; status?: TaskStatus }) =>
      run(async () => {
        if (editor) await updateTask(ws.workspaceId, t.id, body);
        else {
          await updateMyTask(ws.workspaceId, t.id, { title: body.title, due: body.due, start: body.start });
          if (body.status && body.status !== t.status) await updateTask(ws.workspaceId, t.id, { status: body.status });
        }
      }),
    remove: (t: TaskItem) => run(() => (editor ? deleteTask(ws.workspaceId, t.id) : deleteMyTodo(ws.workspaceId, t.id)), "지우지 못했습니다."),
  };
}
