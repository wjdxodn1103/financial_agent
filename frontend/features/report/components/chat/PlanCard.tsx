"use client";

/**
 * 작성 순서 카드(plan_update) — 제안이면 "이 순서로 시작 / 바꾸고 싶어요" 버튼, 확정본이면 진행 상황(n/m)만.
 * 뒤이어 확정 카드가 오면 앞선 제안 카드는 버튼을 접는다(resolved). (OP-FE PlanCard 이식)
 */
import { useState } from "react";
import { useAtomValue } from "jotai";
import { Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { streamingAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import type { PlanCardData } from "../../types";

export function PlanCard({ plan }: { plan: PlanCardData }) {
  const actions = useReportActions();
  const streaming = useAtomValue(streamingAtom);
  const [editing, setEditing] = useState(false);
  const [change, setChange] = useState("");
  const proposal = Boolean(plan.proposed);
  const active = proposal && !plan.resolved;

  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
      <span className="inline-flex items-center rounded-md bg-primary-soft px-2 py-0.5 text-xs font-semibold tracking-wide text-primary">{proposal ? "작성 순서 제안" : "작성 순서"}</span>
      <p className="mt-2 text-base leading-7 font-semibold text-text-primary">{proposal ? "이 순서로 쓰면 어떨까요?" : `${plan.done}/${plan.items.length} 섹션 완료`}</p>
      <div className="mt-3 flex flex-col gap-1.5">
        {plan.items.map((item, i) => {
          const done = !proposal && i < plan.done;
          return (
            <div key={`${i}-${item}`} className="flex items-baseline gap-2.5 text-sm">
              <span className={cn("w-5 shrink-0 text-right font-mono text-xs", done ? "text-primary" : "text-text-secondary")}>{done ? "✓" : i + 1}</span>
              <span className={cn("font-medium", done ? "text-text-secondary line-through" : "text-text-primary")}>{item}</span>
            </div>
          );
        })}
      </div>
      {plan.note && <p className="mt-2 text-xs text-text-secondary">{plan.note}</p>}
      {active && (
        <>
          {editing && (
            <div className="mt-3 flex flex-col gap-1.5">
              <textarea
                value={change}
                onChange={(e) => setChange(e.target.value)}
                rows={2}
                placeholder="예: 리스크 요인을 실적 분석 바로 다음에"
                className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm leading-6 outline-none focus:border-primary-soft-border"
              />
              <div className="flex justify-end gap-1.5">
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                  취소
                </Button>
                <Button size="sm" disabled={!change.trim() || streaming} onClick={() => void actions.send(`작성 순서를 이렇게 바꿔줘: ${change.trim()}`)}>
                  바꿔서 다시 제안
                </Button>
              </div>
            </div>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button disabled={streaming} onClick={() => void actions.send("좋아, 이 순서로 시작하자")}>
              <Check className="size-4" aria-hidden />이 순서로 시작
            </Button>
            <Button variant="outline" disabled={streaming} onClick={() => setEditing((v) => !v)}>
              바꾸고 싶어요
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
