"use client";

/** 👍/👎 — AI 답·섹션·시장 요약·문서. 품질·이용 지표의 '만족도' 원자료(다시 누르면 취소). */
import { useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { giveFeedback } from "../api";
import { useWorkspace } from "../context";

export function Thumbs({ targetKind, targetId, initial = 0, className }: { targetKind: "answer" | "section" | "brief" | "doc"; targetId: string; initial?: number; className?: string }) {
  const ws = useWorkspace();
  const [v, setV] = useState(initial);
  const give = async (t: number) => {
    const prev = v;
    const next = v === t ? 0 : t;
    setV(next);
    try {
      await giveFeedback({ workspaceId: ws.workspaceId, targetKind, targetId, thumbs: next });
    } catch {
      setV(prev);
    }
  };
  const btn = "flex size-6 cursor-pointer items-center justify-center rounded-md text-text-secondary hover:bg-neutral-100";
  return (
    <span className={cn("inline-flex items-center gap-0.5", className)}>
      <button type="button" aria-label="좋아요" aria-pressed={v === 1} onClick={() => void give(1)} className={cn(btn, v === 1 && "text-primary")}>
        <ThumbsUp className="size-3.5" aria-hidden />
      </button>
      <button type="button" aria-label="별로예요" aria-pressed={v === -1} onClick={() => void give(-1)} className={cn(btn, v === -1 && "text-text-primary")}>
        <ThumbsDown className="size-3.5" aria-hidden />
      </button>
    </span>
  );
}
