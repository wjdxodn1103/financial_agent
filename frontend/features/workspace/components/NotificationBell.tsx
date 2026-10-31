"use client";

/** 위쪽 줄 알림함 — 루틴 문서·받은 문서·검토 요청·가정 판정 변화·수집 실패. 안 읽은 수는 30초마다 묻는다(앱 안 알림만). */
import { useCallback, useEffect, useRef, useState } from "react";
import { useSetAtom } from "jotai";
import { Bell, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { getNotificationCount, listNotifications, readNotifications } from "../api";
import { useTasksChanged, useWorkspace } from "../context";
import type { NotificationItem, WorkspaceView } from "../types";
import { assumptionsDrawerAtom, setPendingDrawer } from "../../assumptions/state";

const POLL_MS = 30_000;

function ago(iso: string): string {
  const t = Date.parse(iso);
  if (!t) return "";
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (m < 1) return "방금";
  if (m < 60) return `${m}분 전`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}시간 전`;
  return `${Math.round(h / 24)}일 전`;
}

export function NotificationBell() {
  const ws = useWorkspace();
  const openDrawer = useSetAtom(assumptionsDrawerAtom);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[] | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const refreshCount = useCallback(async () => {
    try {
      setUnread(await getNotificationCount());
    } catch {
      /* 다음 주기에 다시 */
    }
  }, []);

  useEffect(() => {
    void refreshCount();
    const t = window.setInterval(() => void refreshCount(), POLL_MS);
    return () => window.clearInterval(t);
  }, [refreshCount]);
  useTasksChanged(() => void refreshCount());

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void listNotifications().then(
      (r) => {
        if (cancelled) return;
        setItems(r.items);
        setUnread(r.unread);
      },
      () => !cancelled && setItems([]),
    );
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => {
      cancelled = true;
      window.removeEventListener("mousedown", close);
    };
  }, [open]);

  const go = async (n: NotificationItem) => {
    setOpen(false);
    if (!n.read) {
      setItems((xs) => xs?.map((x) => (x.id === n.id ? { ...x, read: true } : x)) ?? null);
      void readNotifications([n.id]).then((r) => setUnread(r.unread), () => undefined);
    }
    const { w, v, s, t } = n.link || {};
    // 가정 판정 알림 — 문서(또는 드라이브)를 열고 가정 서랍을 그 가정에 맞춰 연다
    const r = n.ref as { kind?: string; id?: string; docRef?: string; docKind?: "report" | "data"; title?: string };
    const drawer = r?.kind === "assumption" && r.id && r.docRef ? { docKind: r.docKind ?? "report", docRef: r.docRef, title: r.title ?? "", focusId: r.id } : null;
    if (drawer && w && w !== ws.workspaceId) setPendingDrawer(drawer);
    else if (drawer) setTimeout(() => openDrawer(drawer), 0);
    if (w && w !== ws.workspaceId) {
      const q = new URLSearchParams({ w, ...(v ? { v } : {}), ...(s ? { s } : {}), ...(t ? { t } : {}) });
      window.location.assign(`?${q.toString()}`);
      return;
    }
    if (v === "reports" && s) ws.nav.openReport(s, t ?? null);
    else if (v === "drive" && s) ws.nav.openFolder(s);
    else if (v && s) {
      // 그 화면의 특정 항목(수집 소스·루틴 등) — 주소를 바꾸고 앱의 popstate 읽기에 맡긴다
      const q = new URLSearchParams({ w: ws.workspaceId, v, s, ...(t ? { t } : {}) });
      window.history.pushState(null, "", `?${q.toString()}`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    } else if (v) ws.nav.view(v as WorkspaceView);
  };

  const readAll = async () => {
    try {
      const r = await readNotifications("all");
      setUnread(r.unread);
      setItems((xs) => xs?.map((x) => ({ ...x, read: true })) ?? null);
    } catch {
      /* 그대로 */
    }
  };

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={unread ? `알림 ${unread}개` : "알림"}
        className="relative flex size-8 cursor-pointer items-center justify-center rounded-full text-neutral-600 hover:bg-neutral-100"
      >
        <Bell className="size-[18px]" aria-hidden />
        {unread > 0 && (
          <span className="num absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-[#f04452] px-1 text-center text-[10px] font-bold leading-4 text-white">{unread > 99 ? "99+" : unread}</span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-10 z-50 w-[360px] overflow-hidden rounded-2xl bg-white shadow-xl ring-1 ring-black/5">
          <div className="flex items-center justify-between px-4 py-3">
            <span className="text-[14px] font-bold text-text-primary">알림</span>
            {unread > 0 && (
              <button type="button" onClick={() => void readAll()} className="flex cursor-pointer items-center gap-1 text-[12px] text-text-secondary hover:text-primary">
                <Check className="size-3.5" aria-hidden />
                모두 읽음
              </button>
            )}
          </div>
          <div className="thin-scrollbar max-h-[420px] overflow-y-auto pb-2">
            {items === null && <p className="px-4 py-6 text-center text-[13px] text-text-secondary">불러오는 중…</p>}
            {items?.length === 0 && <p className="px-4 py-6 text-center text-[13px] text-text-secondary">알림이 없습니다.</p>}
            {items?.map((n) => (
              <button
                key={n.id}
                type="button"
                onClick={() => void go(n)}
                className={cn("flex w-full cursor-pointer gap-3 px-4 py-2.5 text-left hover:bg-neutral-50", !n.read && "bg-primary-soft/40")}
              >
                <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", n.read ? "bg-transparent" : "bg-primary")} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-text-primary">{n.title}</span>
                  {n.body && <span className="mt-0.5 line-clamp-2 block text-[12px] text-text-secondary">{n.body}</span>}
                  <span className="mt-0.5 block text-[11px] text-neutral-400">{ago(n.createdAt)}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
