"use client";

import { useEffect } from "react";
import { useAtomValue, useStore } from "jotai";

import { getDocuments } from "../api";
import { documentsAtom, jobsAtom, providerAtom, sessionAtom } from "../atoms";
import type { DocumentCard } from "../types";

/** 3초 × 200 = 10분 뒤에도 안 끝나면 멈춘 것으로 보고 폴링을 그친다(새로고침·새 업로드로 다시 시작) */
const MAX_POLLS = 200;

/** 워크스페이스 데이터 목록 → 이 작업 채팅의 데이터 — 워크스페이스에서 AI 참고를 끈 것은 빼고, 이 작업에서 끈 것(dataExcluded)은 off.
 * 참고 범위를 직접 골랐으면(keep) 지금 보이는 것만 남긴다(범위 계산은 서버 — 폴더 안 새 데이터는 다음 불러오기에 들어온다). */
export function studioDocuments(docs: DocumentCard[], dataExcluded: string[] = [], keep?: Set<string>): DocumentCard[] {
  const off = new Set(dataExcluded);
  return docs.filter((d) => !d.excluded && (!keep || keep.has(d.id))).map((d) => ({ ...d, off: off.has(d.id) }));
}

/** 직접 고른 범위면 지금 목록의 id(studioDocuments 의 keep) */
export function keepOf(store: ReturnType<typeof useStore>): Set<string> | undefined {
  return store.get(sessionAtom)?.dataScope?.mode === "custom" ? new Set(store.get(documentsAtom).map((d) => d.id)) : undefined;
}

/**
 * 자료 처리 폴링 — OP-FE useReferenceJobs 와 같은 "이어 달리기"(앞 요청이 끝난 뒤 다음을 예약) 방식.
 * 처리할 것이 남아 있는 동안만 돈다: 인제스트 대기·처리 중 작업 / 벡터 색인 전 문서(게으른 임베딩) / 카드 정리 중 문서.
 * 끝난 문서부터 목록에 나타나고 바로 검색된다(벡터가 생기기 전에는 BM25).
 */
export function useDocumentJobs(workspaceId: string | null, intervalMs = 3000) {
  const store = useStore();
  const jobs = useAtomValue(jobsAtom);
  const documents = useAtomValue(documentsAtom);
  const provider = useAtomValue(providerAtom);

  const embedOn = Boolean(provider?.embed);
  const activeKey = [
    ...jobs.filter((j) => j.status === "queued" || j.status === "processing").map((j) => `j:${j.id}`),
    ...documents.filter((d) => (embedOn && !d.embedded) || d.enriching).map((d) => `d:${d.id}:${d.embedded}:${d.enriching}`),
  ].join(",");

  useEffect(() => {
    if (!workspaceId || !activeKey) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let polls = 0;
    const tick = async () => {
      if (cancelled || ++polls > MAX_POLLS) return;
      try {
        const d = await getDocuments(workspaceId);
        if (cancelled) return;
        const docs = studioDocuments(d.documents ?? [], store.get(sessionAtom)?.dataExcluded, keepOf(store));
        store.set(documentsAtom, docs);
        store.set(jobsAtom, d.jobs ?? []);
        store.set(sessionAtom, (s) => (s ? { ...s, documentIds: docs.filter((x) => !x.off).map((x) => x.id) } : s));
      } catch {
        /* 일시 오류 — 다음 주기에 다시 */
      }
      if (!cancelled) timer = setTimeout(() => void tick(), intervalMs);
    };
    timer = setTimeout(() => void tick(), intervalMs);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [workspaceId, activeKey, intervalMs, store]);
}
