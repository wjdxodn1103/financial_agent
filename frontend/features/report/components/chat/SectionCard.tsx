"use client";

/**
 * 섹션이 쓰였다는 카드 — 제목·글자 수·출처 수 + 보기/근거/되돌리기.
 * 숫자별 원본은 숫자 출처 탭에서 본다(카드에 판정 요약을 싣지 않는다). 되돌리기는 이 화면에서 받은 카드에만.
 */
import { FileText, Quote, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useReportActions } from "../../hooks/useReportStudio";
import type { SectionUpdate } from "../../types";

export function SectionCard({ msgId, update }: { msgId: string; update: SectionUpdate }) {
  const actions = useReportActions();
  const c = update.checks;

  return (
    <div className={cn("rounded-xl border px-4 py-3", update.undone ? "border-neutral-200 bg-background-gray" : "border-primary-soft-border bg-primary-soft")}>
      <div className="flex items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white text-primary shadow-sm">
          <FileText className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-text-primary">{update.title}</p>
          <p className="mt-0.5 text-xs text-text-secondary">
            {update.undone ? "되돌림" : `${update.chars.toLocaleString()}자${c ? ` · 출처 ${c.citations}곳` : ""}`}
          </p>
        </div>
        {!update.undone && (
          <div className="flex shrink-0 items-center gap-1.5">
            <Button size="sm" variant="outline" onClick={() => actions.openSection(update.step)}>
              보기
            </Button>
            {(c?.citations ?? 0) > 0 && (
              <Button size="sm" variant="ghost" title="이 섹션의 출처 문단 보기" onClick={() => actions.openCitation(update.step, "")}>
                <Quote className="size-3.5" aria-hidden />
                근거
              </Button>
            )}
            {update.revertable && (
              <Button size="sm" variant="ghost" onClick={() => void actions.revertSection(msgId, update.step)}>
                <RotateCcw className="size-3.5" aria-hidden />
                되돌리기
              </Button>
            )}
          </div>
        )}
      </div>
      {!update.undone && (update.warnings?.length ?? 0) > 0 && <p className="mt-2 text-xs text-amber-800">{update.warnings!.join(" ")}</p>}
    </div>
  );
}
