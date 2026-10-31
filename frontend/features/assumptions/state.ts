/** 문서 하나의 가정 목록 — 문서 머리 버튼·본문 표시·서랍이 같이 본다(서랍에서 감시를 켜면 본문 표시도 바로 바뀐다). */
import { useCallback, useEffect } from "react";
import { atom, useAtom } from "jotai";

import { listAssumptions, type Assumption } from "./api";

export const docAssumptionsAtom = atom<{ docRef: string; items: Assumption[] } | null>(null);
/** 열린 서랍 — 문서 머리 '가정'·본문 가정 줄·드라이브 '가정 표시'·홈 카드가 연다 */
export const assumptionsDrawerAtom = atom<{ docKind: "report" | "data"; docRef: string; title: string; focusId?: string } | null>(null);

export function useDocAssumptions(workspaceId: string, docRef: string | null | undefined) {
  const [state, setState] = useAtom(docAssumptionsAtom);
  const reload = useCallback(async () => {
    if (!docRef) return;
    try {
      const items = await listAssumptions(workspaceId, docRef);
      setState({ docRef, items });
    } catch {
      setState({ docRef, items: [] });
    }
  }, [workspaceId, docRef, setState]);
  useEffect(() => {
    if (docRef && state?.docRef !== docRef) void reload();
  }, [docRef]); // eslint-disable-line react-hooks/exhaustive-deps
  const items = docRef && state?.docRef === docRef ? state.items : [];
  const replace = useCallback((a: Assumption) => setState((s) => (s && s.docRef === a.docRef ? { ...s, items: a.status === "dismissed" ? s.items.filter((x) => x.id !== a.id) : s.items.map((x) => (x.id === a.id ? a : x)) } : s)), [setState]);
  const setAll = useCallback((list: Assumption[]) => docRef && setState({ docRef, items: list }), [docRef, setState]);
  return { items, loaded: !!docRef && state?.docRef === docRef, reload, replace, setAll };
}

type DrawerTarget = { docKind: "report" | "data"; docRef: string; title: string; focusId?: string };
const PENDING_KEY = "dcf.openAssumption";

/** 다른 워크스페이스의 알림 — 페이지를 다시 열기 전에 적어 두면 열린 뒤 서랍이 그 가정으로 열린다 */
export function setPendingDrawer(t: DrawerTarget) {
  try {
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(t));
  } catch {
    /* 저장소를 못 쓰면 문서만 연다 */
  }
}

export function takePendingDrawer(): DrawerTarget | null {
  try {
    const raw = sessionStorage.getItem(PENDING_KEY);
    sessionStorage.removeItem(PENDING_KEY);
    return raw ? (JSON.parse(raw) as DrawerTarget) : null;
  } catch {
    return null;
  }
}

/** 판정이 바뀌었고 아직 넘기지 않은 것 */
export const isChanged = (a: Assumption) => !!a.latest?.changed && !a.latest?.acknowledged;
/** 사람이 볼 것 — 바뀌었거나 살펴볼 결과(가정 미충족·재심의 조건 도달)인데 아직 넘기지 않은 것 */
export const needsLook = (a: Assumption) => !!a.latest && !a.latest.acknowledged && (!!a.latest.changed || !!a.latest.alert);
