"use client";

/** 홈 '받은 것' — 멤버가 보낸 문서·데이터·정리한 데이터(메시지·검토 요청). 누르면 연다 — 숫자·문장마다 원문 창으로 근거를 바로 확인. */
import { useEffect, useState } from "react";
import { FileText, Inbox, Table2 } from "lucide-react";
import { listReceived } from "../../api";
import { useTasksChanged, useWorkspace } from "../../context";
import { useOpenSource } from "../../sourceHost";
import type { ShareItem } from "../../types";

function ago(iso: string): string {
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  if (m < 60) return m < 1 ? "방금" : `${m}분 전`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h}시간 전` : `${Math.round(h / 24)}일 전`;
}

export function ReceivedCard() {
  const ws = useWorkspace();
  const openSource = useOpenSource();
  const [items, setItems] = useState<ShareItem[] | null>(null);
  const load = () => void listReceived(ws.workspaceId).then(setItems, () => setItems([]));
  useEffect(load, [ws.workspaceId]); // eslint-disable-line react-hooks/exhaustive-deps
  useTasksChanged(load);

  const open = (s: ShareItem) => {
    if (s.itemKind === "doc") ws.nav.openReport(s.itemId);
    else if (s.itemKind === "data") openSource(s.itemId);
    else ws.nav.view("documents");
  };

  return (
    <section className="rounded-[24px] bg-white px-6 py-5">
      <h2 className="flex items-center gap-2 text-[19px] font-bold text-text-primary">
        받은 것 {items && items.length > 0 && <span className="text-primary">{items.length}</span>}
      </h2>
      <div className="mt-3 flex flex-col">
        {items === null && <p className="py-4 text-[13px] text-text-secondary">불러오는 중…</p>}
        {items?.length === 0 && (
          <p className="flex items-center gap-2 py-4 text-[13px] text-text-secondary">
            <Inbox className="size-4" aria-hidden />
            받은 것이 없습니다.
          </p>
        )}
        {items?.slice(0, 6).map((s) => {
          const Icon = s.itemKind === "table" ? Table2 : FileText;
          return (
            <button key={s.id} type="button" onClick={() => open(s)} className="flex cursor-pointer items-start gap-3 rounded-xl px-2 py-2.5 text-left hover:bg-neutral-50">
              <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-primary-soft text-primary">
                <Icon className="size-4" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-semibold text-text-primary">
                  {s.title}
                  {s.review && <span className="ml-1.5 rounded bg-neutral-100 px-1.5 py-px text-[11px] font-medium text-neutral-700">검토 요청</span>}
                </span>
                <span className="block truncate text-[12px] text-text-secondary">
                  {s.from.name} · {ago(s.createdAt)}
                  {s.message && ` · “${s.message}”`}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
