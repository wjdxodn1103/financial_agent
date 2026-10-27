"use client";

/** 진행 상태 줄 — 턴이 도는 동안 지금 무엇을 하는지 한 줄(컴포저 위 한 곳에만). 옆 "중단"은 컴포저 ■ 와 같은 동작. */
import { useAtomValue } from "jotai";

import { statusStageAtom, streamingAtom } from "../../atoms";
import { statusLabel } from "../../constants";
import { useReportActions } from "../../hooks/useReportStudio";

export function StatusLine() {
  const actions = useReportActions();
  const streaming = useAtomValue(streamingAtom);
  const stage = useAtomValue(statusStageAtom);
  if (!streaming) return null;
  const label = statusLabel(stage);
  return (
    <div className="flex items-center gap-3 py-1">
      <div className="flex items-center gap-2 px-1 text-sm text-text-secondary">
        <span className="dot-bounce flex items-center gap-1" aria-hidden>
          <span />
          <span />
          <span />
        </span>
        {label && <span>{label}…</span>}
      </div>
      <button type="button" onClick={() => actions.stop()} className="cursor-pointer text-xs text-text-secondary underline underline-offset-2 hover:text-text-primary">
        중단
      </button>
    </div>
  );
}
