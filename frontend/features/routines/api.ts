/** 루틴(예약 작성) REST — BE api/routine_routes.py. */
import { jsonInit, req } from "../report/api";

export type RoutineEvery = "daily" | "weekdays" | "weekly" | "manual";

export interface RoutineRunView {
  id: string;
  trigger: "schedule" | "manual" | "replay";
  asOf: string | null;
  status: "running" | "ok" | "partial" | "error";
  reportId: string | null;
  written: number;
  llmCalls: number;
  note: string;
  startedAt: string;
  finishedAt: string | null;
}

export interface Routine {
  id: string;
  name: string;
  call: string;
  formatId: string;
  formatTitle: string;
  dataScope: Record<string, unknown>;
  instruction: string;
  schedule: { every: RoutineEvery; time: string; weekday?: number };
  folderId: string | null;
  titlePattern: string;
  recipients: { all?: boolean; userIds?: string[] };
  reviewerId: string | null;
  owner: { id: string; name: string };
  enabled: boolean;
  source: { kind?: string; sessionId?: string };
  lastRunAt: string | null;
  nextRunAt: string | null;
  lastRun: RoutineRunView | null;
  manualLeft: number;
  canEdit: boolean;
}

export type RoutineInput = Partial<Pick<Routine, "name" | "call" | "formatId" | "instruction" | "schedule" | "folderId" | "titlePattern" | "recipients" | "reviewerId" | "enabled" | "dataScope">> & {
  source?: { kind: string; sessionId?: string };
};

const wid = (w: string) => `/api/workspaces/${encodeURIComponent(w)}`;
export const listRoutines = async (w: string) => (await req<{ routines: Routine[] }>(`${wid(w)}/routines`)).routines ?? [];
export const createRoutine = (w: string, body: RoutineInput) => req<Routine>(`${wid(w)}/routines`, jsonInit("POST", body));
export const updateRoutine = (id: string, body: RoutineInput) => req<Routine>(`/api/routines/${encodeURIComponent(id)}`, jsonInit("PATCH", body));
export const deleteRoutine = (id: string) => req<void>(`/api/routines/${encodeURIComponent(id)}`, { method: "DELETE" });
export const runRoutine = (id: string, asOf?: string) => req<{ started: boolean }>(`/api/routines/${encodeURIComponent(id)}/run`, jsonInit("POST", asOf ? { asOf } : {}));
export const listRoutineRuns = async (id: string) => (await req<{ runs: RoutineRunView[] }>(`/api/routines/${encodeURIComponent(id)}/runs`)).runs ?? [];
