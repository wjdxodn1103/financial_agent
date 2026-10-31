"use client";

/** 본문 속 가정 표시 — 섹션 끝에 그 섹션의 감시 중 가정을 한 줄씩: 문장 · 조건 · 지금 값 · 한 낱말(색 없음). 누르면 가정 서랍의 그 가정. */
import { useAtomValue, useSetAtom } from "jotai";
import { Flag } from "lucide-react";

import { assumptionsDrawerAtom, docAssumptionsAtom, isChanged } from "./state";

export function StepAssumptions({ docRef, step, title }: { docRef: string; step: string; title: string }) {
  const state = useAtomValue(docAssumptionsAtom);
  const open = useSetAtom(assumptionsDrawerAtom);
  if (state?.docRef !== docRef) return null;
  const items = state.items.filter((a) => a.watch && a.step === step);
  if (!items.length) return null;
  return (
    <div className="mt-2 flex flex-col gap-1">
      {items.map((a) => (
        <button
          key={a.id}
          type="button"
          onClick={() => open({ docKind: "report", docRef, title, focusId: a.id })}
          className="flex cursor-pointer items-start gap-2 rounded-md border-l-2 border-neutral-300 bg-neutral-50 px-3 py-1.5 text-left text-[12px] leading-5 hover:bg-neutral-100"
        >
          <Flag className="mt-0.5 size-3 shrink-0 text-neutral-500" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="text-text-primary">
              {a.roleKo} “{a.quote}”
            </span>
            <span className="block text-text-secondary">
              {a.conditionText}
              {a.latest && (
                <>
                  {" · 지금 "}
                  <span className="tabular-nums">{a.latest.value.display || "—"}</span>
                  {" · "}
                  <b className="font-semibold text-text-primary">{a.latest.resultKo}</b>
                  {isChanged(a) && " · 바뀜"}
                </>
              )}
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}
