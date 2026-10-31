"use client";

/** 워크스페이스 어디서나 같은 원문 확인 창 — 드라이브·검색·대시보드·알림에서 숫자·문장을 누르면 연다(Studio 밖).
 * 근거 고정: 서버가 저장 때 얼려 둔 글자·값으로 지금 원문의 같은 자리를 다시 찾는다(BE app/anchors.py). */
import { useCallback } from "react";
import { atom, useAtom, useSetAtom } from "jotai";
import { SourceDialog, type SourceTarget } from "../report/components/viewer/SourceModal";

const wsSourceAtom = atom<SourceTarget | null>(null);

export function WorkspaceSourceHost() {
  const [target, setTarget] = useAtom(wsSourceAtom);
  if (!target) return null;
  return <SourceDialog target={target} onClose={() => setTarget(null)} />;
}

export function useOpenSource() {
  const set = useSetAtom(wsSourceAtom);
  return useCallback((docId: string, chunk?: string | null, cell?: [number, number] | null) => set({ docId, chunk: chunk ?? null, cell: cell ?? null, tick: Date.now() }), [set]);
}
