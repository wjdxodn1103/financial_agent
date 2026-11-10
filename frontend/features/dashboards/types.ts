/** 대시보드 — BE app/dashboards 응답. 위젯 data 는 종류마다 다르다(resolve.widget_data). */
import type { DataIssueView, MarketStatusView, SeriesCard, SeriesView, SourceInfo } from "../data/types";
import type { ShareItem } from "../workspace/types";

export type DashboardKind = "market" | "data" | "workspace";
export type WidgetSize = "s" | "m" | "l" | "full";

export interface BriefFact {
  id: string;
  seriesId: string | null;
  /** 시장 홈 Yahoo 시세에서 온 사실(지수·환율·원자재) — 누르면 그 종목 차트 */
  ticker?: string | null;
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
  peer?: PeerBoardData;
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

/** 시장 홈(BE app/market/home.py) — 지수·환율·원자재는 Yahoo 일봉, 금리는 시장 시계열 카드 */
export interface MarketQuote {
  ticker: string;
  name: string;
  unit: string;
  decimals: number;
  value: number | null;
  date: string | null;
  spark: number[];
  change: number | null;
  pct: number | null;
  high52: number | null;
  low52: number | null;
  fetchedAt: string | null;
}

export interface MarketHomeView {
  groups: { key: "kr" | "global" | "fx" | "cmd"; title: string; items: MarketQuote[] }[];
  rates: SeriesCard[];
  main: string[];
  source: string;
  fetchedAt: string | null;
  refreshing: boolean;
}

export interface MarketChartView {
  ticker: string;
  name: string;
  unit: string;
  decimals: number;
  range: "1M" | "3M" | "6M" | "1Y";
  points: { date: string; value: number }[];
  source: string;
}

export interface DashboardView {
  kind: DashboardKind;
  id: string;
  widgets: Widget[];
  preview: boolean;
  /** 적용된 양식(BE dashboards/templates.py) · 이 구성을 만든 요청 문장 */
  template?: { id: string; label: string } | null;
  prompt?: string;
  draft: { id: string; summary: string; prompt: string; by: string; mine: boolean; at: string | null } | null;
  canEdit: boolean;
  asOf: string | null;
}

/** 피어 비교(양식 peer — BE app/dashboards/peer.py). 값마다 원문 칸(cites)을 달고, 계산값은 식(calc)을 함께 준다. */
export interface PeerCite {
  docId: string;
  chunk: string;
  cell?: [number, number] | null;
  label: string;
}

export interface PeerValue {
  value: number;
  display: string;
  cites: PeerCite[];
  calc: string;
}

export interface PeerCompany {
  name: string;
  code: string;
  ticker: string;
  close?: number;
  date?: string;
  change?: number | null;
  changePct?: number | null;
  returns?: { m1: number | null; m3: number | null; m12: number | null };
  marketCap?: { value: number; display: string; cites: PeerCite[]; calc: string };
}

export interface PeerDoc {
  docId: string;
  title: string;
  issuer: string;
  date: string;
  company: string;
  url: string;
  pages?: number | null;
}

export interface PeerBoardData {
  error?: string;
  companies: PeerCompany[];
  metrics: { id: string; label: string; unit: string; values: (PeerValue | null)[] }[];
  quarters: { categories: string[]; unit: string; series: { name: string; values: (number | null)[]; points: ((PeerCite & { title: string }) | null)[] }[] } | null;
  relative: { base: string; series: { name: string; points: { date: string; value: number }[]; decimals?: number; unit?: string }[] } | null;
  period: string;
  priceDate: string;
  basis: string;
  missing: string[];
  outlook: { title: string; text: string; cites: PeerCite[] }[];
  docs: { news: PeerDoc[]; reports: PeerDoc[]; filings: PeerDoc[] };
}
