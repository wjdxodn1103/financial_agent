/** 어시스턴트 REST — BE api/assistant_routes.py(가이드라인 점검·IC 회의록 정리·심의 준비·하우스뷰 흐름). */
import { jsonInit, req } from "../report/api";
import type { AnchorRef } from "../assumptions/api";

const wid = (id: string) => `/api/workspaces/${encodeURIComponent(id)}`;

export interface GuidelineItem {
  quote: string;
  policyAnchor: AnchorRef | null;
  metric: "asset_class" | "issuer" | "unlisted" | "other";
  label: string;
  limit: string;
  kind: "limit" | "target";
  value: number | null;
  valueDisplay: string;
  how: string;
  result: "ok" | "breach" | "target" | "na";
  resultKo: string;
  gap: number | null;
  anchors: AnchorRef[];
}

export interface GuidelineResult {
  checkedAt: string;
  by: string;
  policy: { docId: string; title: string };
  portfolio: { docId: string; title: string; date: string };
  items: GuidelineItem[];
  counts: Record<"breach" | "ok" | "target" | "na", number>;
}

export interface CommitteeItem {
  kind: "counter" | "open" | "ask";
  kindKo: string;
  text: string;
  assumptionId: string | null;
  quote: string;
  anchor: AnchorRef | null;
  source: string;
}

export interface CommitteeResult {
  docRef: string;
  at: string;
  assumptions: { id: string; quote: string }[];
  past: { id: string; quote: string; docKind: "report" | "data"; docRef: string; docTitle: string; conditionText: string; result: string | null; resultKo: string; value: string | null; anchors: AnchorRef[] }[];
  items: CommitteeItem[];
}

export const getGuideline = async (w: string) => (await req<{ result: GuidelineResult | null }>(`${wid(w)}/guideline`)).result;
export const runGuideline = async (w: string) => (await req<{ result: GuidelineResult }>(`${wid(w)}/guideline/check`, jsonInit("POST", {}))).result;
export const startMinutes = (w: string, docId: string) => req<{ started: boolean; title: string }>(`${wid(w)}/minutes`, jsonInit("POST", { docId }));
export const getCommittee = async (w: string, docRef: string) => (await req<{ result: CommitteeResult | null }>(`${wid(w)}/committee?docRef=${encodeURIComponent(docRef)}`)).result;
export const runCommittee = async (w: string, docKind: "report" | "data", docRef: string) => (await req<{ result: CommitteeResult }>(`${wid(w)}/committee`, jsonInit("POST", { docKind, docRef }))).result;
