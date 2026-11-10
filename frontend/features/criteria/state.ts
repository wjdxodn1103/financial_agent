/** 문서 하나의 검토 제안 — 문서 머리 버튼·섹션 끝 줄·서랍이 같이 본다. 반영하면 'dcf:report-changed' 를 쏴서 열린 문서를 다시 불러온다. */
import { useCallback, useEffect } from "react";
import { atom, useAtom } from "jotai";

import { listProposals, type ProposalView } from "./api";

export const docProposalsAtom = atom<{ reportId: string; items: ProposalView[] } | null>(null);
/** 열린 서랍 — 문서 머리 '검토 제안'·섹션 끝 줄·홈·알림이 연다 */
export const proposalsDrawerAtom = atom<{ reportId: string; title: string; focusId?: string } | null>(null);

export const REPORT_CHANGED = "dcf:report-changed";

export function useDocProposals(workspaceId: string, reportId: string | null | undefined) {
  const [state, setState] = useAtom(docProposalsAtom);
  const reload = useCallback(async () => {
    if (!reportId) return;
    try {
      setState({ reportId, items: await listProposals(workspaceId, reportId) });
    } catch {
      setState({ reportId, items: [] });
    }
  }, [workspaceId, reportId, setState]);
  useEffect(() => {
    if (reportId && state?.reportId !== reportId) void reload();
  }, [reportId]); // eslint-disable-line react-hooks/exhaustive-deps
  const items = reportId && state?.reportId === reportId ? state.items : [];
  const replace = useCallback((p: ProposalView) => setState((s) => (s && s.reportId === p.reportId ? { ...s, items: s.items.map((x) => (x.id === p.id ? p : x)) } : s)), [setState]);
  return { items, loaded: !!reportId && state?.reportId === reportId, reload, replace };
}

type DrawerTarget = { reportId: string; title: string; focusId?: string };
const PENDING_KEY = "dcf.openProposal";

/** 다른 워크스페이스의 알림 — 페이지를 다시 연 뒤 서랍이 그 제안으로 열린다 */
export function setPendingProposal(t: DrawerTarget) {
  try {
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(t));
  } catch {
    /* 저장소를 못 쓰면 문서만 연다 */
  }
}

export function takePendingProposal(): DrawerTarget | null {
  try {
    const raw = sessionStorage.getItem(PENDING_KEY);
    sessionStorage.removeItem(PENDING_KEY);
    return raw ? (JSON.parse(raw) as DrawerTarget) : null;
  } catch {
    return null;
  }
}
