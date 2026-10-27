"use client";

/**
 * 채널 메시지 속 숫자의 원본 — BE(channel/numbers.py)가 메시지의 (지표·기간·값) 을 원장에서 찾은 결과를 판정 문구 없이 원본으로만 잇는다.
 * 누르면 오른쪽에 원장 값의 원문 칸이 열린다. 원장에 없는 숫자는 표시하지 않는다.
 */
import { FileText } from "lucide-react";

import { cn } from "@/lib/utils";
import type { NumberCheck } from "../../types";

export function ChannelNumberChecks({ checks, onOpen, align }: { checks: NumberCheck[]; onOpen: (docId: string, chunk: string, cell: [number, number] | null) => void; align?: "end" }) {
  if (!checks.length) return null;
  return (
    <div className={cn("mt-1 flex max-w-[80%] flex-col gap-0.5", align === "end" && "items-end")}>
      {checks.map((c, i) => {
        const what = `${c.metric} ${c.period}${c.basis ? `·${c.basis}` : ""}`;
        const src = `${c.ref.label}${c.ref.page ? ` p.${c.ref.page}` : ""}`;
        const value = c.status === "conflict" ? (c.values ?? []).join(" / ") : c.ref.display;
        return (
          <button key={i} type="button" title="원본 보기" onClick={() => onOpen(c.ref.docId, c.ref.chunk, c.ref.cell)} className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-neutral-200 bg-white px-1.5 py-0.5 text-left text-[11px] leading-4 text-text-secondary hover:text-primary hover:underline">
            <FileText className="size-3 shrink-0" aria-hidden />
            <span>
              {what} {value} · {src}
            </span>
          </button>
        );
      })}
    </div>
  );
}
