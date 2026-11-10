/** 가정 감시(문서 속) REST — BE api/assumption_routes.py. 메뉴 없이 문서 머리·드라이브 데이터 줄·홈에서 쓴다. */
import { jsonInit, req } from "../report/api";

const wid = (id: string) => `/api/workspaces/${encodeURIComponent(id)}`;

/** 원문 위치(BE app/anchors.py) — 문단·칸 주소 + 얼려 둔 글자·값 */
export interface AnchorRef {
  docId?: string;
  chunk?: string;
  cell?: [number, number] | null;
  quote?: string;
  rowLabel?: string;
  colLabel?: string;
  value?: { raw?: string };
  kind?: "report" | "data";
  sessionId?: string;
  step?: string;
}

export interface AssumptionValue {
  display?: string;
  value?: number;
  unit?: string;
  period?: string;
  base?: string;
  rule?: string;
}

export interface AssumptionCheckView {
  id: string;
  at: string;
  asOf: string | null;
  result: string;
  resultKo: string;
  value: AssumptionValue;
  anchors: AnchorRef[];
  changed: boolean;
}

export interface Assumption {
  id: string;
  docKind: "report" | "data";
  docRef: string;
  docTitle: string;
  step: string | null;
  quote: string;
  anchor: AnchorRef;
  target: { name?: string; ticker?: string };
  kind: "numeric" | "qualitative";
  condition: { metric?: string; ledgerMetric?: string; period?: string; op?: string; threshold?: number; unit?: string };
  /** assumption = 가정(충족·미충족) | trigger = 재심의 조건(도달·미도달) */
  role: "assumption" | "trigger";
  roleKo: string;
  conditionText: string;
  basis: AnchorRef[];
  watch: boolean;
  status: "candidate" | "watching" | "dismissed";
  latest: {
    result: string;
    resultKo: string;
    value: AssumptionValue;
    at: string;
    asOf: string | null;
    changed: boolean;
    acknowledged: boolean;
    anchors: AnchorRef[];
    prev: string | null;
    prevKo: string | null;
    /** 살펴볼 결과 — 가정의 미충족·반박, 재심의 조건의 도달 */
    alert: boolean;
    agendaId?: string;
    agendaStatus?: "writing" | "error";
  } | null;
  history: AssumptionCheckView[];
}

export interface TodayPayload {
  assumptions: Assumption[];
  watching: number;
  routineDocs: { id: string; title: string; routine: string; asOf: string | null; status: string | null; updatedAt: string }[];
  /** 내 문서에 열린 검토 제안(판단 기준) */
  proposals?: { id: string; reportId: string; reportTitle: string; directionKo: string; changed: string; criterion?: string; createdAt: string }[];
  /** 내가 승인할 수 있는 판단 기준 초안·수정안 수 */
  criteriaPending?: number;
}

export const listAssumptions = async (w: string, docRef?: string) =>
  (await req<{ assumptions: Assumption[] }>(`${wid(w)}/assumptions${docRef ? `?docRef=${encodeURIComponent(docRef)}` : ""}`)).assumptions ?? [];
export const extractAssumptions = async (w: string, docKind: "report" | "data", docRef: string) =>
  (await req<{ assumptions: Assumption[] }>(`${wid(w)}/assumptions/extract`, jsonInit("POST", { docKind, docRef }))).assumptions ?? [];
export const patchAssumption = (id: string, body: Record<string, unknown>) => req<Assumption>(`/api/assumptions/${encodeURIComponent(id)}`, jsonInit("PATCH", body));
export const checkAssumption = (id: string, asOf?: string | null) => req<Assumption>(`/api/assumptions/${encodeURIComponent(id)}/check`, jsonInit("POST", { asOf: asOf || null }));
/** 백그라운드로 시작 — 다 쓰면 알림. 돌려받는 것은 지금 가정(latest.agendaStatus = writing) */
export const writeAgenda = (id: string) => req<Assumption>(`/api/assumptions/${encodeURIComponent(id)}/agenda`, jsonInit("POST", {}));
export const getToday = (w: string) => req<TodayPayload>(`${wid(w)}/today`);
