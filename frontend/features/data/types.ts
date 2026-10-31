/** 수집 소스·시장 데이터·데이터 품질 — BE app/pipeline·app/market 응답 그대로(camelCase). */

export type SourceKind = "series" | "rss" | "edgar" | "folder";
export type ScheduleEvery = "daily" | "weekdays" | "hourly" | "weekly" | "manual";

export interface SourceSchedule {
  every: ScheduleEvery;
  times: string[];
  weekday?: number;
}

export interface SourceRunView {
  id: string;
  trigger: "schedule" | "manual" | "replay" | "retry";
  asOf: string | null;
  status: "running" | "ok" | "partial" | "error" | "skipped";
  new: number;
  failed: number;
  note: string;
  startedAt: string;
  finishedAt: string | null;
}

export interface SourceInfo {
  id: string;
  scope: "company" | "workspace";
  workspaceId: string;
  kind: SourceKind;
  kindKo: string;
  name: string;
  params: Record<string, unknown>;
  schedule: SourceSchedule;
  target: { folderId?: string };
  createdBy: string;
  enabled: boolean;
  status: string;
  lastRunAt: string | null;
  nextRunAt: string | null;
  items: number;
  failedItems: number;
  lastRun: SourceRunView | null;
  canEdit: boolean;
  watchDir?: string;
  mode?: "live" | "fixture";
}

export interface SourceItemView {
  id: string;
  key: string;
  title: string;
  url: string;
  publishedAt: string | null;
  docId: string | null;
  status: "ok" | "error";
  error: string | null;
  retries: number;
  fetchedAt: string;
  meta: Record<string, unknown>;
}

export interface SeriesMeta {
  id: string;
  name: string;
  group: string;
  unit: string;
  change: "bp" | "pct" | "pp";
  freq: "D" | "M";
  decimals: number;
  virtual: boolean;
  calc: string[] | null;
  providers: string[];
}

export interface EdgarCompany {
  cik: number;
  ticker: string;
  name: string;
  virtual?: boolean;
}

export interface SourceCatalog {
  series: SeriesMeta[];
  feeds: { url: string; issuer: string }[];
  edgarMode: "live" | "fixture";
  fixtureCompanies: EdgarCompany[];
  forms: string[];
}

export interface Change {
  value: number;
  unit: string;
  display: string;
  from: { date: string; value: number; display: string };
}

export interface SeriesCard {
  id: string;
  name: string;
  group: string;
  unit: string;
  decimals: number;
  freq: "D" | "M";
  source: string | null;
  sourceLabel: string;
  virtual: boolean;
  fallback: boolean;
  value: number | null;
  display?: string;
  date: string | null;
  changes: Partial<Record<"d1" | "w1" | "m1", Change>>;
  spark: number[];
  status: "ok" | "stale" | "empty";
}

export interface MarketBoard {
  asOf: string;
  groups: { group: string; series: SeriesCard[] }[];
}

export interface SeriesView {
  id: string;
  name: string;
  unit: string;
  decimals: number;
  source: string | null;
  sourceLabel: string;
  virtual: boolean;
  range: string;
  points: { date: string; value: number }[];
}

export interface ProviderState {
  status: "ok" | "error" | "nokey";
  error?: string;
  at?: string;
  rows?: number;
  check?: boolean;
}

export interface MarketStatusView {
  series: {
    id: string;
    name: string;
    group: string;
    virtual: boolean;
    providerInUse: string | null;
    providerLabel: string;
    fallback: boolean;
    lastOkAt: string | null;
    lastDate: string | null;
    lastError: string | null;
    providers: Record<string, ProviderState>;
  }[];
  providers: { provider: string; label: string; ok: number; error: number; nokey: number; lastAt: string | null }[];
}

export interface DataIssueView {
  id: string;
  kind: "missing" | "outlier" | "disagree" | "stale" | "unit" | "doc_mismatch" | "ingest_failed";
  kindKo: string;
  seriesId: string | null;
  sourceId: string | null;
  detail: Record<string, unknown>;
  detectedAt: string;
  resolvedAt: string | null;
}
