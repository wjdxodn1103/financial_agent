/** 판단 기준·검토 제안 REST — BE api/criteria_routes.py. 기준은 문서 검수 ▸ 판단 기준, 제안은 문서 머리 '검토 제안'·섹션 끝 줄·홈·알림에서. */
import { jsonInit, req } from "../report/api";
import type { AnchorRef } from "../assumptions/api";

const wid = (id: string) => `/api/workspaces/${encodeURIComponent(id)}`;

export type CriterionStatus = "draft" | "active" | "archived" | "rejected";

export interface CriterionView {
  id: string;
  key: string;
  version: number;
  scope: "company" | "workspace";
  scopeKo: string;
  workspaceId: string;
  status: CriterionStatus;
  statusKo: string;
  title: string;
  when: string;
  kind: "numeric" | "qualitative" | "stance";
  conditionText: string;
  condition: { metric?: string; ledgerMetric?: string; period?: string; op?: string; threshold?: number; unit?: string };
  direction: "expand" | "hold" | "reduce" | "review";
  directionKo: string;
  applies: { name?: string; ticker?: string; assetClass?: string; stance?: string };
  limit: { op?: string; threshold?: number; unit?: string };
  source: { docKind?: "report" | "data"; docRef?: string; docTitle?: string; step?: string | null; quote?: string; anchor?: AnchorRef | null };
  origin: { kind?: "extract" | "revision"; reportId?: string; reportTitle?: string; relation?: "new" | "refine" | "conflict"; why?: string; via?: string };
  conflicts: { id: string; key: string; version: number; title: string; why: string; by: "code" | "ai" }[];
  note: string;
  createdBy: string;
  approvedBy: string | null;
  approvedAt: string | null;
  createdAt: string;
  base: { id: string; version: number; title: string; conditionText: string; directionKo: string } | null;
  diff: { field: string; before: unknown; after: unknown }[];
  canApprove: boolean;
}

export interface CriteriaPayload {
  criteria: CriterionView[];
  canApprove: { company: boolean; workspace: boolean };
  canExtract: { company: boolean; workspace: boolean };
}

export interface ProposalSentence {
  step: string;
  original: string;
  plain: string;
  revised: string | null;
  why: string;
}

export interface ProposalView {
  id: string;
  workspaceId: string;
  reportId: string;
  reportTitle: string;
  target: { name?: string; ticker?: string };
  direction: string;
  directionKo: string;
  criterion: { id?: string; key?: string; version?: number; title?: string; scope?: string; quote?: string; anchor?: AnchorRef | null; docTitle?: string };
  check: { result: string; value: { display?: string; period?: string; base?: string }; anchors: AnchorRef[]; asOf: string | null };
  headroom: { criterionId: string; title: string; display: string; gap: number; within: boolean; anchors: AnchorRef[] }[];
  changed: string;
  explanation: string;
  sentences: ProposalSentence[];
  evidence: { data?: AnchorRef[]; decision?: { title?: string; quote?: string; anchor?: AnchorRef | null } | null };
  status: "open" | "applied" | "agenda" | "dismissed";
  statusKo: string;
  result: { versionId?: string; agendaId?: string; agendaStatus?: "writing" | "error"; applied?: number };
  createdAt: string;
  decidedAt: string | null;
  /** 승인된 문서 — 고치지 않고 재심의 안건으로 */
  approved: boolean;
  canApply: boolean;
  canAct: boolean;
}

export const listCriteria = (w: string) => req<CriteriaPayload>(`${wid(w)}/criteria`);
export const extractCriteria = (w: string, body: { docKind: "report" | "data"; docRef: string; scope: "company" | "workspace" }) =>
  req<CriteriaPayload & { made: number; found: number }>(`${wid(w)}/criteria/extract`, jsonInit("POST", body));
export const patchCriterion = (id: string, body: { title?: string; when?: string; direction?: string; condition?: CriterionView["condition"]; note?: string }) =>
  req<CriterionView>(`/api/criteria/${encodeURIComponent(id)}`, jsonInit("PATCH", body));
export const decideCriterion = (id: string, approve: boolean, note = "") => req<CriterionView>(`/api/criteria/${encodeURIComponent(id)}/decide`, jsonInit("POST", { approve, note }));
export const criterionVersions = async (id: string, w: string) => (await req<{ versions: CriterionView[] }>(`/api/criteria/${encodeURIComponent(id)}/versions?workspaceId=${encodeURIComponent(w)}`)).versions ?? [];
export const scanCriteria = (w: string, asOf?: string | null) => req<{ proposals: number; targets: number }>(`${wid(w)}/criteria/scan`, jsonInit("POST", { asOf: asOf || null }));

export const listProposals = async (w: string, reportId?: string, status = "open,applied,agenda") =>
  (await req<{ proposals: ProposalView[] }>(`${wid(w)}/proposals?status=${encodeURIComponent(status)}${reportId ? `&reportId=${encodeURIComponent(reportId)}` : ""}`)).proposals ?? [];
export const applyProposal = (id: string, picks?: number[]) => req<ProposalView>(`/api/proposals/${encodeURIComponent(id)}/apply`, jsonInit("POST", { picks: picks ?? null }));
/** 백그라운드로 시작 — 다 쓰면 알림(result.agendaStatus = writing) */
export const proposalAgenda = (id: string) => req<ProposalView>(`/api/proposals/${encodeURIComponent(id)}/agenda`, jsonInit("POST", {}));
export const dismissProposal = (id: string, note = "") => req<ProposalView>(`/api/proposals/${encodeURIComponent(id)}/dismiss`, jsonInit("POST", { note }));

/** 본문 인용 토큰([@문서#문단])을 뺀 글자 */
export const plainText = (s: string) => (s || "").replace(/\[@[^\]]+\]/g, "").trim();
