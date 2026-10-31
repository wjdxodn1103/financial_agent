/** 대시보드 REST(BE api/dashboard_routes.py). */
import { jsonInit, req } from "../report/api";
import type { BriefView, DashboardKind, DashboardView } from "./types";

const q = (o: Record<string, string | number | undefined>) => {
  const p = Object.entries(o).filter(([, v]) => v !== undefined && v !== "" && v !== 0);
  return p.length ? `?${new URLSearchParams(p.map(([k, v]) => [k, String(v)])).toString()}` : "";
};

export const getDashboard = (kind: DashboardKind, workspaceId: string, preview = false) =>
  kind === "workspace"
    ? req<DashboardView>(`/api/workspaces/${encodeURIComponent(workspaceId)}/dashboard${q({ preview: preview ? 1 : 0 })}`)
    : req<DashboardView>(`/api/dashboards/${kind}${q({ workspaceId, preview: preview ? 1 : 0 })}`);

export const proposeDashboard = (kind: DashboardKind, workspaceId: string, instruction: string) =>
  kind === "workspace"
    ? req<DashboardView>(`/api/workspaces/${encodeURIComponent(workspaceId)}/dashboard/propose`, jsonInit("POST", { instruction }))
    : req<DashboardView>(`/api/dashboards/${kind}/propose${q({ workspaceId })}`, jsonInit("POST", { instruction }));

export const decideDraft = (draftId: string, approve: boolean) => req<DashboardView>(`/api/dashboard/drafts/${encodeURIComponent(draftId)}/${approve ? "approve" : "discard"}`, jsonInit("POST", {}));
export const getBrief = (date?: string) => req<BriefView>(`/api/market/brief${q({ date })}`);
export const regenerateBrief = () => req<BriefView>("/api/market/brief/regenerate", jsonInit("POST", {}));
