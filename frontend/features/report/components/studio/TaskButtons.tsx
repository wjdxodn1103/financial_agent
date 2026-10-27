"use client";

/**
 * 작업 화면 왼쪽 위 — 데이터 설정 · 작업 불러오기 · 저장하기.
 * 대화·문서는 늘 자동으로 남는다. 저장하기 = 작업 이름 정하기, 불러오기 = 내 작업(빈 작업 빼고)에서 골라 열기·지우기.
 */
import { useEffect, useRef, useState } from "react";
import { useAtomValue, useSetAtom } from "jotai";
import { Database, FileText, FolderOpen, Loader2, MessageSquare, Save, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { listReports } from "../../../workspace/api";
import { useWorkspace } from "../../../workspace/context";
import { deleteSession } from "../../api";
import { canChatAtom, dataSettingsOpenAtom, hasDocAtom, messagesAtom, reportAtom, sessionAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import { useAppNav } from "../../nav";
import type { SessionListItem } from "../../types";

const btn = "flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg px-2.5 text-[13px] font-medium text-neutral-700 transition-colors hover:bg-neutral-100 disabled:cursor-default disabled:opacity-40";

function day(iso?: string): string {
  return iso ? new Date(iso).toLocaleDateString("ko-KR", { month: "short", day: "numeric" }) : "";
}

/** 지금 작업의 이름 — 정한 제목, 없으면 첫 질문(목록 이름과 같은 규칙) */
function useTaskTitle(): string {
  const session = useAtomValue(sessionAtom);
  const messages = useAtomValue(messagesAtom);
  const report = useAtomValue(reportAtom);
  const hasDoc = useAtomValue(hasDocAtom);
  const firstAsk = messages.find((m) => m.role === "user")?.text.slice(0, 40);
  return session?.setup.title || firstAsk || (hasDoc ? (report?.title ?? "") : "");
}

function LoadDialog({ onClose }: { onClose: () => void }) {
  const ws = useWorkspace();
  const nav = useAppNav();
  const session = useAtomValue(sessionAtom);
  const [items, setItems] = useState<SessionListItem[] | null>(null);
  const typeTitle = (id: string) => ws.meta.reportTypes.find((t) => t.id === id)?.title ?? id;

  useEffect(() => {
    // 내 작업만(대화는 개인 — 남의 문서는 드라이브에서 연다), 아무것도 안 한 빈 작업은 뺀다
    void listReports(ws.workspaceId)
      .then((xs) => setItems(xs.filter((x) => x.createdBy === ws.me.id && !x.empty)))
      .catch(() => setItems([]));
  }, [ws.workspaceId, ws.me.id]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const remove = async (id: string) => {
    if (!window.confirm("이 작업을 지울까요? 대화와 문서가 함께 지워집니다(만든 표·올린 데이터 파일은 남습니다).")) return;
    try {
      await deleteSession(id);
      setItems((xs) => (xs ?? []).filter((x) => x.id !== id));
      if (id === session?.id) nav.back();
    } catch {
      toast.error("지우지 못했습니다.", { position: "top-center" });
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="flex max-h-[80vh] w-full max-w-[560px] flex-col overflow-hidden rounded-[24px] bg-white shadow-xl">
        <div className="flex items-center gap-3 px-6 pt-6 pb-3">
          <h2 className="flex-1 text-[20px] font-bold tracking-tight text-text-primary">작업 불러오기</h2>
          <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-4 pb-5">
          {items === null && (
            <p className="flex items-center gap-2 px-2 py-6 text-[14px] text-text-secondary">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              불러오는 중
            </p>
          )}
          {items?.length === 0 && <p className="px-2 py-8 text-center text-[14px] text-text-secondary">저장된 작업이 없습니다.</p>}
          {items?.map((s) => (
            <div key={s.id} className={cn("group flex items-center gap-1 rounded-xl hover:bg-neutral-50", s.id === session?.id && "bg-primary-soft hover:bg-primary-soft")}>
              <button
                type="button"
                onClick={() => {
                  onClose();
                  if (s.id !== session?.id) nav.open(s.id);
                }}
                className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 px-2.5 py-2.5 text-left"
              >
                <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-xl", s.hasDoc === false ? "bg-neutral-100 text-neutral-500" : "bg-primary-soft text-primary")}>
                  {s.hasDoc === false ? <MessageSquare className="size-4" aria-hidden /> : <FileText className="size-4" aria-hidden />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-semibold text-text-primary">{s.title}</span>
                  <span className="block truncate text-[12px] text-text-secondary">{[s.hasDoc === false ? "대화" : `${typeTitle(s.reportType)} · ${s.written}/${s.sections} 섹션`, day(s.updatedAt)].filter(Boolean).join(" · ")}</span>
                </span>
              </button>
              <button type="button" title="지우기" aria-label="지우기" onClick={() => void remove(s.id)} className="mr-2 shrink-0 cursor-pointer rounded-lg p-1.5 text-neutral-400 opacity-0 group-hover:opacity-100 hover:bg-white hover:text-red-600">
                <Trash2 className="size-4" aria-hidden />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** anchor = 버튼과 창을 감싼 칸 — 그 밖을 누르면 닫는다(버튼을 다시 누르면 닫힘) */
function SavePopover({ anchor, onClose }: { anchor: React.RefObject<HTMLDivElement | null>; onClose: () => void }) {
  const actions = useReportActions();
  const current = useTaskTitle();
  const [name, setName] = useState(current);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onDown = (e: MouseEvent) => !anchor.current?.contains(e.target as Node) && onClose();
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [anchor, onClose]);

  const save = async () => {
    if (!name.trim()) return;
    setBusy(true);
    const ok = await actions.setSetup({ title: name.trim() });
    setBusy(false);
    if (ok) {
      toast.success("작업을 저장했습니다.", { position: "top-center" });
      onClose();
    }
  };

  return (
    <div className="absolute top-full left-0 z-40 mt-1 w-[320px] rounded-2xl bg-white p-3 shadow-[0_8px_24px_rgba(0,27,55,0.16)]">
      <p className="px-1 text-[13px] font-semibold text-text-primary">작업 이름</p>
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && void save()}
        placeholder="예: 가온전자 2024 실적 점검"
        className="mt-2 h-10 w-full rounded-xl bg-neutral-100 px-3 text-[14px] outline-none focus:bg-white focus:ring-2 focus:ring-primary/30"
      />
      <div className="mt-2.5 flex justify-end gap-1.5">
        <button type="button" onClick={onClose} className="h-8 cursor-pointer rounded-lg bg-neutral-100 px-3 text-[13px] font-semibold text-neutral-700 hover:bg-neutral-200">
          취소
        </button>
        <button type="button" disabled={busy || !name.trim()} onClick={() => void save()} className="flex h-8 cursor-pointer items-center gap-1 rounded-lg bg-primary px-3 text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40">
          {busy && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
          저장
        </button>
      </div>
    </div>
  );
}

export function TaskButtons() {
  const canChat = useAtomValue(canChatAtom);
  const openSettings = useSetAtom(dataSettingsOpenAtom);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const saveRef = useRef<HTMLDivElement>(null);
  return (
    <div className="flex min-w-0 items-center gap-0.5">
      {canChat && (
        <button type="button" onClick={() => openSettings(true)} className={btn}>
          <Database className="size-4 text-primary" aria-hidden />
          데이터 설정
        </button>
      )}
      <button type="button" onClick={() => setLoading(true)} className={btn}>
        <FolderOpen className="size-4 text-neutral-500" aria-hidden />
        작업 불러오기
      </button>
      {canChat && (
        <div ref={saveRef} className="relative">
          <button type="button" onClick={() => setSaving((v) => !v)} className={btn}>
            <Save className="size-4 text-neutral-500" aria-hidden />
            저장하기
          </button>
          {saving && <SavePopover anchor={saveRef} onClose={() => setSaving(false)} />}
        </div>
      )}
      {loading && <LoadDialog onClose={() => setLoading(false)} />}
    </div>
  );
}
