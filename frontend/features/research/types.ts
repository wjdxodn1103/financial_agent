/** AI 채팅 — BE app/research (대화·출처 달린 표·표 양식). */
import type { ChartBlock, NoteBlock, StreamError, TableBlock, ToolRun } from "../report/types";

export type SubjectKind = "company" | "document" | "period" | "label";
export type ItemType = "number" | "text" | "calc";
export type Orientation = "subjects_as_rows" | "items_as_rows";
export type TemplateScope = "company" | "workspace" | "user";

export interface TemplateItem {
  key: string;
  label: string;
  type: ItemType;
  metric?: string;
  unit?: string;
  decimals?: number;
  periodOffset?: number;
  instruction?: string;
  formula?: string;
  hidden?: boolean;
}

export interface TemplateSpec {
  name: string;
  desc?: string;
  subject: { kind: SubjectKind; label: string };
  /** null = 행은 매번 정함(열만 고정) */
  rows: { label: string; docId?: string }[] | null;
  items: TemplateItem[];
  /** 열도 매번 정함(질문 표) */
  itemsOpen: boolean;
  orientation: Orientation;
  inputs: { key: "period" | "basis"; label: string; default: string }[];
  /** 차트 양식 — 표를 채운 뒤 이 모양으로 차트를 그린다 */
  chart?: { type: "bar" | "line"; horizontal?: boolean; seriesLabels?: string[] };
}

export interface ResearchTemplate {
  id: string;
  scope: TemplateScope;
  builtin: boolean;
  name: string;
  spec: TemplateSpec;
  ownerId?: string;
  owner?: string;
  updatedAt?: string;
}

/** 에셋 — 표, 표에서 만든 차트(kind=chart), 리서치 메모(kind=note) */
export interface ResearchTable {
  id: string;
  kind: "table" | "chart" | "note";
  title: string;
  status: "running" | "done" | "error";
  saved: boolean;
  chatId: string;
  mine: boolean;
  createdBy: string;
  updatedAt: string;
  templateId: string | null;
  spec: {
    name: string;
    subject: { kind: SubjectKind; label: string };
    orientation: Orientation;
    itemsOpen: boolean;
  };
  items: TemplateItem[];
  subjects: { label: string; docId?: string }[];
  inputs: { period?: string; basis?: string };
  period: { key: string; label: string } | null;
  progress: { done?: number; total?: number };
  folderId: string | null;
  /** 차트면 — 종류·원 표·단위가 달라 뺀 열 */
  chart: { type: "bar" | "line"; source: string | null; sourceTitle: string | null; dropped: string[] } | null;
  block: TableBlock | ChartBlock | NoteBlock;
}

/** 드라이브 ▸ 에셋 목록 한 줄(BE research/assets.asset_item) */
export interface AssetItem {
  id: string;
  kind: "table" | "chart" | "note";
  title: string;
  status: "running" | "done" | "error";
  saved: boolean;
  mine: boolean;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  period: string | null;
  /** 이 에셋을 만든 내 AI 작업 */
  taskId: string | null;
  rows: number;
  cols: number;
  chartType?: "bar" | "line";
  sourceTitle?: string | null;
  /** 메모의 출처 수 */
  cites?: number;
  /** 올린 문서에서 꺼낸 표면 그 문서 */
  sourceDoc?: string | null;
}

export interface ResearchMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  tools?: ToolRun[];
  tables?: { id: string; title: string }[];
  error?: StreamError;
  streaming?: boolean;
  aborted?: boolean;
}

export interface ChatSummary {
  id: string;
  title: string;
  updatedAt: string;
}

export interface ChatPayload {
  chat: {
    id: string;
    title: string;
    workspaceId: string;
    currentTableId: string | null;
  };
  messages: ResearchMessage[];
  tables: ResearchTable[];
}

export type ResearchEvent =
  | { type: "status"; stage: string }
  | { type: "meta"; sessionId?: string; model?: string }
  | { type: "text"; delta: string }
  | { type: "text_replace"; text: string }
  | {
      type: "tool_start";
      id: string;
      name: string;
      args?: Record<string, string>;
    }
  | {
      type: "tool_end";
      id: string;
      name: string;
      status: "done" | "error";
      summary?: string;
    }
  | { type: "table_update"; table: ResearchTable }
  | { type: "template_saved"; template: ResearchTemplate }
  | { type: "error"; message: string; code?: string }
  | { type: "done" };
