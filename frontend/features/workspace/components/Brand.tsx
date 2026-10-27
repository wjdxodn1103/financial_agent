/** 서비스 이름표 — 이름을 한 곳에서 바꾼다. DCF = Document Creation & Fact-check(현금흐름할인법과 겹치는 이름). */
import { ScanSearch } from "lucide-react";

import { cn } from "@/lib/utils";

export const APP_NAME = "DCF";
export const APP_TAGLINE = "Document Creation & Fact-check";

export function Brand({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-primary text-white">
        <ScanSearch className="size-[18px]" aria-hidden />
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
