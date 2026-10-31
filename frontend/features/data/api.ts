/** 수집 소스·시장 데이터·데이터 품질 REST(BE api/pipeline_routes.py). */
import { jsonInit, req } from "../report/api";
import type { DataIssueView, EdgarCompany, MarketBoard, MarketStatusView, SeriesView, SourceCatalog, SourceInfo, SourceItemView, SourceRunView } from "./types";

const wid = (id: string) => `/api/workspaces/${encodeURIComponent(id)}`;

export const listSources = (w: string) => req<{ sources: SourceInfo[]; isAdmin: boolean; kinds: { id: string; label: string }[] }>(`${wid(w)}/sources`);
export const getSourceCatalog = () => req<SourceCatalog>("/api/sources/catalog");
export const searchEdgarCompanies = async (q: string) => (await req<{ companies: EdgarCompany[] }>(`/api/sources/edgar/companies?q=${encodeURIComponent(q)}`)).companies ?? [];
export const createSource = (w: string, body: Partial<SourceInfo> & { kind: string }) => req<SourceInfo>(`${wid(w)}/sources`, jsonInit("POST", body));
export const updateSource = (id: string, body: Partial<SourceInfo>) => req<SourceInfo>(`/api/sources/${encodeURIComponent(id)}`, jsonInit("PATCH", body));
export const deleteSource = (id: string) => req<void>(`/api/sources/${encodeURIComponent(id)}`, { method: "DELETE" });
export const runSource = (id: string, asOf?: string) => req<{ started: boolean }>(`/api/sources/${encodeURIComponent(id)}/run`, jsonInit("POST", asOf ? { asOf } : {}));
export const listSourceRuns = async (id: string) => (await req<{ runs: SourceRunView[] }>(`/api/sources/${encodeURIComponent(id)}/runs`)).runs ?? [];
export const listSourceItems = async (id: string) => (await req<{ items: SourceItemView[] }>(`/api/sources/${encodeURIComponent(id)}/items`)).items ?? [];
export const retrySourceItem = (itemId: string) => req<{ started: boolean }>(`/api/sources/items/${encodeURIComponent(itemId)}/retry`, jsonInit("POST", {}));

export const getMarketBoard = (asOf?: string) => req<MarketBoard>(`/api/market/board${asOf ? `?asOf=${asOf}` : ""}`);
export const getMarketSeries = (id: string, range = "1Y") => req<SeriesView>(`/api/market/series/${encodeURIComponent(id)}?range=${range}`);
export const getMarketStatus = () => req<MarketStatusView>("/api/market/status");
export const refreshMarket = () => req<{ started: boolean }>("/api/market/refresh", jsonInit("POST", {}));
export const listDataIssues = async (w?: string) => (await req<{ issues: DataIssueView[] }>(`/api/data/issues${w ? `?workspaceId=${encodeURIComponent(w)}` : ""}`)).issues ?? [];
