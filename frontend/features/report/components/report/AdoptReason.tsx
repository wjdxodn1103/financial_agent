"use client";

/** 채택 사유 한 줄 — "이 값 채택"을 누르면 그 값 아래에 열린다(브라우저 prompt 대신). Enter = 채택, Esc = 취소. 사유는 결정 기록에 남는다. */
import { useState } from "react";
import { Check, Loader2 } from "lucide-react";

export function AdoptReason({ display, busy, onSubmit, onCancel }: { display: string; busy: boolean; onSubmit: (reason: string) => void; onCancel: () => void }) {
  const [reason, setReason] = useState("");
  return (
    <div className="flex w-full items-center gap-1.5">
      <input
        autoFocus
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        onKeyDown={(e) => {
          if (e.nativeEvent.isComposing) return;
          if (e.key === "Enter") onSubmit(reason.trim());
          if (e.key === "Escape") onCancel();
        }}
        placeholder={`${display} 채택 사유(선택) — 예: 회사 공시(IR) 기준`}
        className="min-w-0 flex-1 rounded-md border border-neutral-200 bg-white px-2 py-1 text-[11px] outline-none focus:border-primary"
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => onSubmit(reason.trim())}
        className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-md bg-primary px-2 py-1 text-[11px] font-medium text-white hover:bg-primary-hover disabled:opacity-50"
      >
        {busy ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Check className="size-3" aria-hidden />}
        채택
      </button>
      <button type="button" disabled={busy} onClick={onCancel} className="shrink-0 cursor-pointer rounded-md px-1.5 py-1 text-[11px] text-text-secondary hover:bg-neutral-100">
        취소
      </button>
    </div>
  );
}
