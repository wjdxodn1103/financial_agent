"use client";

/** 본문 속 검토 제안 표시 — 섹션 끝에 그 섹션 문장이 걸린 열린 제안을 한 줄씩. 누르면 검토 제안 서랍의 그 제안. */
import { useAtomValue, useSetAtom } from "jotai";
import { Scale } from "lucide-react";

import { docProposalsAtom, proposalsDrawerAtom } from "./state";

export function StepProposals({ reportId, step, title }: { reportId: string; step: string; title: string }) {
  const state = useAtomValue(docProposalsAtom);
  const open = useSetAtom(proposalsDrawerAtom);
  if (state?.reportId !== reportId) return null;
  const items = state.items.filter((p) => p.status === "open" && p.sentences.some((s) => s.step === step));
  if (!items.length) return null;
  return (
    <div className="mt-2 flex flex-col gap-1">
      {items.map((p) => (
        <button
          key={p.id}
          type="button"
          onClick={() => open({ reportId, title, focusId: p.id })}
          className="flex cursor-pointer items-start gap-2 rounded-md border-l-2 border-neutral-400 bg-neutral-50 px-3 py-1.5 text-left text-[12px] leading-5 hover:bg-neutral-100"
        >
          <Scale className="mt-0.5 size-3 shrink-0 text-neutral-500" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="text-text-primary">
              {p.directionKo} 검토 제안 · {p.criterion.title} v{p.criterion.version}
            </span>
            <span className="block text-text-secondary">{p.changed}</span>
          </span>
        </button>
      ))}
    </div>
  );
}
