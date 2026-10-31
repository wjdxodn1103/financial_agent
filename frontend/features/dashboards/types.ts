/** 대시보드 — BE app/dashboards 응답. 위젯 data 는 종류마다 다르다(resolve.widget_data). */
import type { DataIssueView, MarketStatusView, SeriesCard, SeriesView, SourceInfo } from "../data/types";
import type { ShareItem } from "../workspace/types";

export type DashboardKind = "market" | "data" | "workspace";
export type WidgetSize = "s" | "m" | "l" | "full";

export interface BriefFact {
  id: string;
  seriesId: string | null;
  name: string;
  value: string;
  unit?: string;
  date?: string;
  source?: string;
  virtual: boolean;
  changes?: Partial<Record<"d1" | "w1" | "m1", string>>;
  text: string;
}

export interface BriefView {
  date: string | null;
  summary: string[];
  judgement: string[];
  facts: BriefFact[];
  dropped: string[];
  model?: string;
  dates: string[];
  createdAt: string | null;
}

export interface IngestStats {
  companyDocs: number;
  workspaceDocs: number;
  chunks: number;
  figures: number;
  observations: number;
  series: number;
  sources: number;
  items: number;
  itemsWeek: number;
}

export interface WidgetData {
  error?: string;
  cards?: SeriesCard[];
  rows?: SeriesCard[];
  series?: SeriesView[] | MarketStatusView["series"];
  sources?: SourceInfo[];
  providers?: MarketStatusView["providers"];
  issues?: DataIssueView[];
  shares?: ShareItem[];
  docs?: { id: string; title: string; routine: string; asOf: string | null; status: string | null; updatedAt: string }[];
  tasks?: { id: string; title: string; due: string; status: string }[];
  items?: { id: string; quote: string; docTitle: string; docRef: string; docKind?: "report" | "data"; roleKo?: string; result: string | null; condition: string; value: string | null; changed: boolean; at: string | null }[];
  metrics?: { id: string; label: string; value: string; detail?: string }[];
  text?: string;
  houseview?: HouseViewFlow;
}

/** 하우스뷰 흐름(BE app/assistants/houseview.py) — 분기 × 자산군 입장, 칸마다 그 문장 원문 */
export interface HouseViewFlow {
  periods: string[];
  rows: { asset: string; cells: Record<string, { stance: "positive" | "neutral" | "negative"; stanceKo: string; quote: string; docId: string; chunk: string; changed: boolean }> }[];
  pending: number;
  assumptions: { id: string; quote: string; docRef: string; period: string; condition: string; result: string | null; value: string | null }[];
  docs: Record<string, { docId: string; title: string }>;
}

export interface Widget {
  id: string;
  type: string;
  title: string;
  params: Record<string, unknown>;
  size: WidgetSize;
  data: WidgetData & Partial<BriefView> & Partial<IngestStats>;
}

export interface DashboardView {
  kind: DashboardKind;
  id: string;
  widgets: Widget[];
  preview: boolean;
  draft: { id: string; summary: string; prompt: string; by: string; mine: boolean; at: string | null } | null;
  canEdit: boolean;
  asOf: string | null;
}
