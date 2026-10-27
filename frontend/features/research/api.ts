/** AI 채팅 API — BE app/api/research_routes.py */
import { jsonInit, req } from "../report/api";
import type { ImportCard, ImportFormat, ReportTypeInfo, SessionPayload } from "../report/types";
import type { AssetItem, ChatPayload, ChatSummary, ResearchTable, ResearchTemplate, TemplateScope, TemplateSpec } from "./types";

const wid = (id: string) => `/api/workspaces/${encodeURIComponent(id)}/research`;
const rc = (id: string) => `/api/research/chats/${encodeURIComponent(id)}`;
const rt = (id: string) => `/api/research/tables/${encodeURIComponent(id)}`;

export const listChats = async (w: string) => (await req<{ chats: ChatSummary[] }>(`${wid(w)}/chats`)).chats;
export const createChat = (w: string, title = "") => req<ChatPayload>(`${wid(w)}/chats`, jsonInit("POST", { title }));
export const getChat = (id: string) => req<ChatPayload>(rc(id));
export const renameChat = (id: string, title: string) => req<{ id: string; title: string }>(rc(id), jsonInit("PATCH", { title }));
export const deleteChat = (id: string) => req<void>(rc(id), { method: "DELETE" });
export const cancelChatTurn = (id: string) => req<{ cancelled: boolean }>(`${rc(id)}/cancel`, { method: "POST" });
export const chatTurnPath = (id: string) => `${rc(id)}/chat`;

export const getTable = (id: string) => req<ResearchTable>(rt(id));
export const patchTable = (
  id: string,
  body: {
    title?: string;
    orientation?: string;
    saved?: boolean;
    folderId?: string | null;
  },
) => req<ResearchTable>(rt(id), jsonInit("PATCH", body));
export const deleteTable = (id: string) => req<void>(rt(id), { method: "DELETE" });
export const tableExportPath = (id: string, fmt: "docx" | "xlsx") => `${rt(id)}/export.${fmt}`;
/** 표 → 차트(막대·꺾은선) — 이 작업의 결과에 두고 그 차트를 지금 보는 것으로 */
export const addChart = (sessionId: string, tableId: string, type: "bar" | "line") => req<SessionPayload>(`/api/sessions/${encodeURIComponent(sessionId)}/charts`, jsonInit("POST", { tableId, type }));
/** 대화의 답 하나 → 메모(근거 아님) */
export const addNote = (sessionId: string, msgId: string) => req<SessionPayload>(`/api/sessions/${encodeURIComponent(sessionId)}/notes`, jsonInit("POST", { msgId }));

/** 올린 자료 속 표 — 목록 · 에셋으로 꺼내기 · 비슷한 문서에서 만든 같은 모양 */
export interface DocTable {
  chunk: string;
  no: number;
  page: number | null;
  caption: string;
  unit: string | null;
  rows: number;
  cols: number;
  header: string[];
}
export interface SimilarAssets {
  same: { id: string; title: string; createdBy: string; mine: boolean; chunk: string | null }[];
  similar: { chunk: string; no: number; caption: string; page: number | null; score: number; asset: { id: string; title: string; createdBy: string; mine: boolean; sourceDocLabel: string } }[];
}
const wdoc = (w: string, d: string) => `/api/workspaces/${encodeURIComponent(w)}/documents/${encodeURIComponent(d)}`;
export const docTables = (w: string, d: string) => req<{ tables: DocTable[] }>(`${wdoc(w, d)}/tables`);
export const docTableAsset = (w: string, d: string, chunk: string) => req<ResearchTable>(`${wdoc(w, d)}/tables/${encodeURIComponent(chunk)}/asset`, { method: "POST" });
export const similarAssets = (w: string, d: string) => req<SimilarAssets>(`${wdoc(w, d)}/similar-assets`);
export const applySimilar = (w: string, d: string, picks: { chunk: string; assetId: string }[]) => req<{ tables: ResearchTable[] }>(`${wdoc(w, d)}/similar-assets`, jsonInit("POST", { picks }));

/** 드라이브 ▸ 에셋 — q 는 낱말·종류(표·차트·메모)·범위(내 것·공유)·날짜(지난주 등)를 함께 읽는다 */
export const listAssets = (w: string, q = "", kind?: "table" | "chart" | "note", scope?: "mine" | "shared") => {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  if (kind) p.set("kind", kind);
  if (scope) p.set("scope", scope);
  return req<{ assets: AssetItem[]; query: { terms: string[]; kind?: string | null; scope?: string | null; dateLabel?: string | null } }>(`/api/workspaces/${encodeURIComponent(w)}/assets?${p}`);
};
/** 표를 문서 섹션 뒤에 넣기(지금 표의 복사본) */
export const insertTable = (sessionId: string, tableId: string, step: string) => req<SessionPayload>(`/api/sessions/${encodeURIComponent(sessionId)}/tables`, jsonInit("POST", { tableId, step }));

// 양식 샘플(Word·PDF) — 올린 뒤 /chat {import} 턴이 카드를 낸다
export const uploadSample = (sessionId: string, file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return req<{ importId: string; name: string }>(`/api/sessions/${encodeURIComponent(sessionId)}/imports`, { method: "POST", body: fd });
};
export const importItem = (sessionId: string, importId: string, n: number, body: { action: "register" | "skip"; name?: string; scope?: TemplateScope; spec?: Partial<TemplateSpec> }) =>
  req<{ item: ImportCard }>(`/api/sessions/${encodeURIComponent(sessionId)}/imports/${encodeURIComponent(importId)}/items/${n}`, jsonInit("POST", body));
export const importFormat = (sessionId: string, importId: string, body: { name?: string; scope?: TemplateScope }) =>
  req<{ format: ImportFormat; items: ImportCard[] }>(`/api/sessions/${encodeURIComponent(sessionId)}/imports/${encodeURIComponent(importId)}/format`, jsonInit("POST", body));
/** 등록한 리포트 양식(rt:) — 워크스페이스 meta 의 reportTypes 에 합친다 */
export const listReportTypes = async (w: string) => (await req<{ reportTypes: ReportTypeInfo[] }>(`/api/workspaces/${encodeURIComponent(w)}/report-types`)).reportTypes;
export const deleteReportType = (id: string) => req<void>(`/api/report-types/${encodeURIComponent(id)}`, { method: "DELETE" });

export const listTemplates = async (w: string) => (await req<{ templates: ResearchTemplate[] }>(`${wid(w)}/templates`)).templates;
export const createTemplate = (
  w: string,
  body: {
    name: string;
    scope: TemplateScope;
    spec?: Partial<TemplateSpec>;
    fromTableId?: string;
    keepRows?: boolean;
  },
) => req<ResearchTemplate>(`${wid(w)}/templates`, jsonInit("POST", body));
export const patchTemplate = (id: string, body: { name?: string; spec?: Partial<TemplateSpec> }) => req<ResearchTemplate>(`/api/research/templates/${encodeURIComponent(id)}`, jsonInit("PATCH", body));
export const deleteTemplate = (id: string) =>
  req<void>(`/api/research/templates/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
