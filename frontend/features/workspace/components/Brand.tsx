/** 서비스 이름표 — 이름을 한 곳에서 바꾼다. AssociateLM = 운용역의 일을 맡는 AI 어소시에이트(2026-11-03, 옛 이름 ANCHOR·DCF). */
import { BriefcaseBusiness } from "lucide-react";

import { cn } from "@/lib/utils";

export const APP_NAME = "AssociateLM";
export const APP_TAGLINE = "금융 AI 어시스턴트";

export function Brand({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-primary text-white">
        <BriefcaseBusiness className="size-[18px]" aria-hidden />
      </span>
      {!compact && (
        <span className="leading-tight">
          <span className="block text-[15px] font-bold tracking-tight text-text-primary">{APP_NAME}</span>
          <span className="block text-[11px] text-text-secondary">{APP_TAGLINE}</span>
        </span>
      )}
    </div>
  );
}
