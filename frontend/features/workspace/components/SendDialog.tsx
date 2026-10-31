"use client";

/** 보내기 — 문서·데이터·정리한 데이터를 멤버에게(메시지·검토 요청). 받는 사람은 알림함·홈 '받은 것'에서 연다. 앱 안 알림만. */
import { useState } from "react";
import { Check, X } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ApiError } from "../../report/api";
import { sendItem } from "../api";
import { useWorkspace } from "../context";

export function SendDialog({ item, onClose }: { item: { kind: "doc" | "data" | "table"; id: string; title: string }; onClose: () => void }) {
  const ws = useWorkspace();
  const [to, setTo] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const others = (ws.detail?.members ?? []).map((m) => m.user).filter((u) => u.id !== ws.me.id);
  const canReview = to.length === 1 || item.kind !== "doc";

  const submit = async () => {
    if (!to.length) return;
    setBusy(true);
    try {
      await sendItem(ws.workspaceId, { itemKind: item.kind, itemId: item.id, to, message, review: review && canReview });
      toast.success(review ? "검토를 요청했습니다." : "보냈습니다.", { position: "top-center" });
      onClose();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "보내지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="w-full max-w-[440px] rounded-[24px] bg-white p-6 shadow-xl">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[18px] font-bold text-text-primary">보내기</h2>
            <p className="mt-0.5 truncate text-[13px] text-text-secondary">{item.title}</p>
          </div>
          <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        <div className="mt-4 flex max-h-[220px] flex-col gap-0.5 overflow-y-auto">
          {others.map((m) => {
            const on = to.includes(m.id);
            return (
              <button key={m.id} type="button" onClick={() => setTo((xs) => (on ? xs.filter((x) => x !== m.id) : [...xs, m.id]))} className="flex cursor-pointer items-center gap-2.5 rounded-xl px-2.5 py-2 text-left hover:bg-neutral-50">
                <span className={cn("flex size-4 items-center justify-center rounded border", on ? "border-primary bg-primary text-white" : "border-neutral-300")}>{on && <Check className="size-3" aria-hidden />}</span>
                <span className="text-[14px] font-medium text-text-primary">{m.name}</span>
                <span className="text-[12px] text-text-secondary">{m.title}</span>
              </button>
            );
          })}
        </div>
        <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3} placeholder="메시지(선택)" className="mt-3 w-full resize-none rounded-xl bg-neutral-100 px-3 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-primary/30" />
        <label className={cn("mt-2 flex items-center gap-2 text-[13px]", canReview ? "cursor-pointer text-text-primary" : "text-neutral-400")}>
          <input type="checkbox" checked={review && canReview} disabled={!canReview} onChange={(e) => setReview(e.target.checked)} />
          검토 요청{item.kind === "doc" && " (한 사람)"}
        </label>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="h-10 cursor-pointer rounded-xl px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-100">
            닫기
          </button>
          <button type="button" disabled={!to.length || busy} onClick={() => void submit()} className="h-10 cursor-pointer rounded-xl bg-primary px-5 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
            보내기
          </button>
        </div>
      </div>
    </div>
  );
}

export const APPROVAL_KO: Record<string, string> = { draft: "AI 초안", review: "검토 중", approved: "승인" };
