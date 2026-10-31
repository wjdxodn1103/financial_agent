"use client";

/** 루틴 등록·고치기 — 양식·지시·일정·올릴 폴더·받는 사람·검토 담당. 대화의 확인 카드·작업의 '루틴으로 저장'도 이 창으로 미리 채워 연다. */
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ApiError } from "../report/api";
import { getDrive } from "../workspace/api";
import { useWorkspace } from "../workspace/context";
import { createRoutine, updateRoutine, type Routine, type RoutineEvery, type RoutineInput } from "./api";

const EVERY: { id: RoutineEvery; label: string }[] = [
  { id: "daily", label: "매일" },
  { id: "weekdays", label: "평일" },
  { id: "weekly", label: "매주" },
  { id: "manual", label: "손으로만" },
];

export function RoutineDialog({ initial, editing, onClose, onSaved }: { initial?: RoutineInput & { folderName?: string }; editing?: Routine; onClose: () => void; onSaved: (r: Routine) => void }) {
  const ws = useWorkspace();
  const base = editing ?? initial ?? {};
  const [name, setName] = useState(base.name ?? "");
  const [formatId, setFormatId] = useState(base.formatId ?? "");
  const [instruction, setInstruction] = useState(base.instruction ?? "");
  const [every, setEvery] = useState<RoutineEvery>(base.schedule?.every ?? "weekdays");
  const [time, setTime] = useState(base.schedule?.time ?? "07:00");
  const [weekday, setWeekday] = useState(base.schedule?.weekday ?? 0);
  const [folderId, setFolderId] = useState<string>(base.folderId ?? "");
  const [allMembers, setAllMembers] = useState(base.recipients?.all ?? true);
  const [userIds, setUserIds] = useState<string[]>(base.recipients?.userIds ?? []);
  const [reviewerId, setReviewerId] = useState(base.reviewerId ?? "");
  const [folders, setFolders] = useState<{ id: string; name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const formats = ws.meta.reportTypes.filter((t) => t.id !== "free");
  const members = (ws.detail?.members ?? []).map((m) => m.user);

  useEffect(() => {
    void getDrive(ws.workspaceId).then((d) => {
      setFolders(d.tree.map((f) => ({ id: f.id, name: f.name })));
      const want = (initial as { folderName?: string } | undefined)?.folderName;
      if (want && !base.folderId) {
        const hit = d.tree.find((f) => f.name.includes(want) || want.includes(f.name));
        if (hit) setFolderId(hit.id);
      }
    }, () => undefined);
  }, [ws.workspaceId]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!name.trim() || !formatId) return toast.error("이름과 양식을 정하세요.", { position: "top-center" });
    const body: RoutineInput = {
      name: name.trim(),
      formatId,
      instruction,
      schedule: { every, time, ...(every === "weekly" ? { weekday } : {}) },
      folderId: folderId || null,
      recipients: { all: allMembers, userIds: allMembers ? [] : userIds },
      reviewerId: reviewerId || null,
      ...(editing ? {} : { source: initial?.source ?? { kind: "manual" } }),
    };
    setBusy(true);
    try {
      const r = editing ? await updateRoutine(editing.id, body) : await createRoutine(ws.workspaceId, body);
      toast.success(editing ? "루틴을 고쳤습니다." : "루틴을 등록했습니다.", { position: "top-center" });
      onSaved(r);
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "저장하지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  const chip = (on: boolean) => cn("cursor-pointer rounded-lg px-2.5 py-1 text-[12px] font-medium", on ? "bg-primary-soft text-primary" : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200");
  const label = "mt-4 block text-[13px] font-semibold text-text-secondary";
  const input = "mt-1 h-10 w-full rounded-xl bg-neutral-100 px-3 text-[14px] outline-none focus:ring-2 focus:ring-primary/30";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="flex max-h-[90vh] w-full max-w-[580px] flex-col overflow-hidden rounded-[24px] bg-white shadow-xl">
        <div className="flex items-center justify-between px-6 pt-5 pb-2">
          <h2 className="text-[19px] font-bold text-text-primary">{editing ? "루틴 고치기" : "루틴 등록"}</h2>
          <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-6 pb-4">
          <label className={label}>이름</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="해외주식 동향 브리핑" className={input} />
          <p className="mt-1 text-[11px] text-text-secondary">대화창에서 /{name.trim() || "이름"} 로 부를 수 있습니다.</p>

          <label className={label}>양식</label>
          <select value={formatId} onChange={(e) => setFormatId(e.target.value)} className={input}>
            <option value="">양식 고르기</option>
            {formats.map((f) => (
              <option key={f.id} value={f.id}>
                {f.title}
              </option>
            ))}
          </select>

          <label className={label}>지시</label>
          <textarea value={instruction} onChange={(e) => setInstruction(e.target.value)} rows={3} placeholder="매번 무엇을 어떤 관점으로 쓸지" className="mt-1 w-full resize-none rounded-xl bg-neutral-100 px-3 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-primary/30" />

          <label className={label}>언제</label>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {EVERY.map((e) => (
              <button key={e.id} type="button" onClick={() => setEvery(e.id)} className={chip(every === e.id)}>
                {e.label}
              </button>
            ))}
            {every === "weekly" && (
              <select value={weekday} onChange={(e) => setWeekday(Number(e.target.value))} className="h-8 rounded-lg bg-neutral-100 px-2 text-[12px]">
                {["월", "화", "수", "목", "금", "토", "일"].map((d, i) => (
                  <option key={d} value={i}>
                    {d}요일
                  </option>
                ))}
              </select>
            )}
            {every !== "manual" && <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="h-8 rounded-lg bg-neutral-100 px-2 text-[12px]" />}
          </div>

          <label className={label}>올릴 폴더</label>
          <select value={folderId} onChange={(e) => setFolderId(e.target.value)} className={input}>
            <option value="">드라이브 맨 위</option>
            {folders.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>

          <label className={label}>알릴 사람</label>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <button type="button" onClick={() => setAllMembers(true)} className={chip(allMembers)}>
              워크스페이스 전원
            </button>
            <button type="button" onClick={() => setAllMembers(false)} className={chip(!allMembers)}>
              고른 멤버
            </button>
          </div>
          {!allMembers && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {members.map((m) => (
                <button key={m.id} type="button" onClick={() => setUserIds((xs) => (xs.includes(m.id) ? xs.filter((x) => x !== m.id) : [...xs, m.id]))} className={chip(userIds.includes(m.id))}>
                  {m.name}
                </button>
              ))}
            </div>
          )}

          <label className={label}>검토 담당(선택)</label>
          <select value={reviewerId} onChange={(e) => setReviewerId(e.target.value)} className={input}>
            <option value="">없음</option>
            {members
              .filter((m) => m.id !== ws.me.id)
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} {m.title}
                </option>
              ))}
          </select>
        </div>
        <div className="flex justify-end gap-2 border-t border-neutral-100 px-6 py-4">
          <button type="button" onClick={onClose} className="h-10 cursor-pointer rounded-xl px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-100">
            닫기
          </button>
          <button type="button" disabled={busy} onClick={() => void save()} className="h-10 cursor-pointer rounded-xl bg-primary px-5 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
            {editing ? "저장" : "등록"}
          </button>
        </div>
      </div>
    </div>
  );
}
