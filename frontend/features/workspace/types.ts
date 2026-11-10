/** 워크스페이스 계약 타입 — backend app/services/workspace_service.py 응답 그대로(camelCase). */
import type { DocumentCard, Role, UserInfo } from "../report/types";

export interface WorkspaceSettings {
  offHour: string;
  connectors?: Record<string, boolean>;
}

export interface WorkspaceInfo {
  id: string;
  name: string;
  kind: string;
  description: string;
  settings: WorkspaceSettings;
  documentCount: number;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

export interface WorkspaceListItem extends WorkspaceInfo {
  role: Role;
  members: number;
}

export interface Member {
  user: UserInfo;
  role: Role;
  lastSeenAt: string | null;
}

export interface WorkspaceDetail {
  workspace: WorkspaceInfo;
  me: { role: Role; lastSeenAt: string | null };
  members: Member[];
  users: UserInfo[];
}

export type WorkspaceView = "home" | "schedule" | "tasks" | "search" | "channel" | "research" | "reports" | "documents" | "company" | "assets" | "formats" | "ledger" | "reviews" | "requests" | "members" | "sources" | "market" | "dataStatus" | "dashboard" | "routines" | "quality" | "guideline" | "calendar" | "criteria";

// ─── 드라이브(BE drive.py) ───
export type FolderAccess = "all" | "private" | "members";

export interface DriveFolderCard {
  id: string;
  name: string;
  access: FolderAccess;
  items: number;
  createdBy: string;
  updatedAt: string;
}

export interface DriveDocCard {
  id: string;
  title: string;
  reportType: string;
  written: number;
  sections: number;
  createdBy: string;
  updatedAt: string;
  /** 문서 상태 — draft(AI 초안)·review(검토 중)·approved(승인) */
  approval?: "draft" | "review" | "approved" | null;
  routine?: boolean;
}

/** 보내기 — backend app/sharing.py view() */
export interface ShareItem {
  id: string;
  itemKind: "doc" | "data" | "table";
  itemId: string;
  title: string;
  from: { id: string; name: string };
  to: string[];
  message: string;
  review: boolean;
  createdAt: string;
}

export interface DriveListing {
  folder: { id: string; name: string; access: FolderAccess; memberIds: string[]; createdBy: string; canShare: boolean } | null;
  path: { id: string; name: string }[];
  folders: DriveFolderCard[];
  docs: DriveDocCard[];
  data: import("../report/types").DocumentCard[];
  /** 드라이브에 저장한 표·차트·메모(정리한 데이터) — chatId 는 내 AI 작업에서 만든 것일 때만(그 작업으로 연다) */
  tables: { id: string; kind?: "table" | "chart" | "note"; title: string; rows: number; cols: number; createdBy: string; updatedAt: string; chatId: string | null }[];
  jobs: import("../report/types").IngestJob[];
  members: { id: string; name: string }[];
  /** 나에게 보이는 폴더 전체(왼쪽 폴더 트리·옮기기 대상 고르기) */
  tree: { id: string; name: string; parentId: string | null; access: FolderAccess }[];
}

export interface DriveSearch {
  folders: { id: string; name: string; path: string; items: number }[];
  data: { id: string; label: string; fileType: string; shared: boolean; personal?: boolean; path: string }[];
}

// ─── 통합 검색 (BE app/search.py) ───
export interface SearchItem {
  kind: "asset" | "doc" | "file" | "folder" | "document" | "figure" | "record" | "report" | "message" | "task";
  title: string;
  text?: string;
  sub?: string;
  at?: string | null;
  id?: string;
  docId?: string | null;
  chunk?: string | null;
  cell?: [number, number] | null;
  reportId?: string;
  step?: string;
  key?: string;
  threadId?: string | null;
  /** 에셋을 만든 내 AI 작업 */
  taskId?: string | null;
}
export interface SearchResult {
  query: string;
  groups: { kind: SearchItem["kind"]; label: string; items: SearchItem[] }[];
}

// ─── 근거 원장 ───
export interface Figure {
  fid: string;
  id: string;
  doc: string;
  docLabel: string;
  chunk: string;
  cell: [number, number] | null;
  metric: string;
  metricKey: string;
  period: string;
  periodKey: string;
  basis: string | null;
  raw: string;
  display: string;
  value: number;
  percent: boolean;
  unit: string;
  currency: string | null;
  abs: number;
  heading?: string | null;
  page?: number | null;
  sheet?: string | null;
  source: "table" | "dart" | string;
  unitKnown?: boolean;
}

export interface LedgerValue {
  figureIds: string[];
  raw: string;
  display: string;
  unit: string;
  abs: number;
}

export interface LedgerGroup {
  key: string;
  metric: string;
  metricKey: string;
  period: string;
  periodKey: string;
  basis: string | null;
  unitUnknown: boolean;
  figureIds: string[];
  documents: number;
  conflict: boolean;
  values: LedgerValue[];
  chosen: { figureId: string; reason?: string; chosenBy?: string; chosenAt?: string } | null;
  value: { figureId: string; raw: string; display: string; unit: string; abs: number } | null;
}

export interface Ledger {
  figures: Figure[];
  groups: LedgerGroup[];
  stats: { figures: number; groups: number; conflicts: number; resolved: number; documents: number };
}

// ─── 데이터 연결 ───
export interface ConnectorInfo {
  id: string;
  title: string;
  desc: string;
  ready: boolean;
  hint: string;
}

export interface DartCompany {
  corpCode: string;
  corpName: string;
  stockCode: string;
  listed: boolean;
}

export interface LibraryEntry {
  id: string;
  docId: string;
  card: DocumentCard;
  note: string;
  publishedBy: string;
  publishedById: string;
  from: string;
  at: string;
  /** 이 워크스페이스에 이미 붙었는가 */
  attached: boolean;
}

export interface EdgarCompany {
  cik: number;
  ticker: string;
  name: string;
}

export interface EcosTable {
  statCode: string;
  statName: string;
  cycle: string;
}

export interface EcosItem {
  itemCode: string;
  itemName: string;
  group: string;
  cycle: string;
  start: string;
  end: string;
  count: number;
  unit: string;
}

// ─── 문서 검수 ───
export type FindingRule = "mismatch" | "unsourced" | "calc" | "internal" | "ok";

export interface FindingEvidence {
  fid: string;
  docId: string;
  docLabel: string;
  chunk: string;
  cell: [number, number] | null;
  display: string;
  page?: number | null;
  sheet?: string | null;
}

export interface Finding {
  id: string;
  rule: FindingRule;
  severity: "high" | "medium" | "info";
  claimId: string;
  message: string;
  formula?: string;
  expected?: FindingEvidence;
  evidence: FindingEvidence[];
  taskId?: string;
  claim: { metric: string; period: string; basis: string | null; raw: string; quote: string; chunk: string; cell?: [number, number] | null; kind: string; source: string };
}

export interface ReviewSummary {
  claims: number;
  counts: Record<FindingRule, number>;
  unverifiable: number;
  mode?: "llm" | "rule";
  proposed?: number;
  rejected?: number;
  /** 추출이 빠뜨려 코드가 훑어 더 찾은 숫자 수 */
  swept?: number;
  /** 지표 이름을 못 읽어 대조하지 않은 숫자 — 사람이 볼 것 */
  missed?: { chunk: string; raw: string; quote: string }[];
  referenceDocs?: number;
  /** 앞선 검수(같은 자료·이전 판) 대비 — 해소된 지적의 작업 항목은 자동 완료 */
  carry?: {
    previousReviewId: string;
    previousDocId: string;
    previousLabel: string;
    resolved: { rule: FindingRule; metric: string; period: string; before: string; taskId?: string | null }[];
    carried: { rule: FindingRule; metric: string; period: string; before: string; after?: string; taskId?: string | null }[];
    new: number;
    autoDone: number;
  };
}

export interface TaskItem {
  id: string;
  title: string;
  detail: string;
  assigneeId: string | null;
  /** 마감(기간의 끝) YYYY-MM-DD, 없으면 "" */
  due: string;
  /** 기간의 시작 — 하루짜리면 "" */
  start: string;
  status: "todo" | "doing" | "review" | "done";
  source: { kind?: string; reviewId?: string; findingId?: string; docId?: string; recordId?: string; reportId?: string };
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

export interface Review {
  id: string;
  docId: string;
  docLabel: string;
  fileName: string;
  status: "running" | "done" | "error";
  summary: ReviewSummary | Record<string, never>;
  error: string | null;
  createdBy: string;
  createdAt: string;
  finishedAt: string | null;
  findings?: Finding[];
  tasks?: TaskItem[];
}

// ─── 채널·팀 기록·브리핑 ───
/** 채널 메시지 속 숫자 ↔ 원장 대조(BE channel/numbers.py) */
export interface NumberCheck {
  raw: string;
  metric: string;
  period: string;
  basis: string | null;
  status: "match" | "mismatch" | "conflict";
  chosen?: boolean;
  documents?: number;
  values?: string[];
  sameAs?: string | null;
  ref: { docId: string; label: string; chunk: string; cell: [number, number] | null; page: number | null; display: string };
}

export interface ChannelMsg {
  id: string;
  userId: string | null;
  author: string;
  kind: "user" | "agent" | "system";
  text: string;
  /** 답글이면 스레드 첫 메시지 id */
  threadId?: string | null;
  meta: {
    numberChecks?: NumberCheck[];
    mentions?: string[];
    attachments?: { docId: string; label: string }[];
    askAgent?: boolean;
    pending?: boolean;
    replyTo?: string;
    cites?: Record<string, { docId: string; chunk: string; label: string; page?: number | null }>;
    /** 시스템 알림(검토 요청 등)이 가리키는 리포트 */
    report?: { id: string; title: string };
    taskId?: string;
  };
  createdAt: string;
}

export interface RecordQuote {
  messageId: string | null;
  userId: string | null;
  author: string;
  text: string;
  at: string;
}

export interface TeamRecordItem {
  id: string;
  type: "decision" | "directive" | "convention" | "todo" | "question";
  typeKo: string;
  text: string;
  quotes: RecordQuote[];
  authorId: string | null;
  author: string;
  scope: string;
  status: "candidate" | "confirmed" | "dismissed" | "superseded";
  source: { kind?: string; trigger?: string; assigneeId?: string | null; due?: string; card?: string };
  confirmedBy: string;
  confirmedAt: string | null;
  createdAt: string;
  canConfirm?: boolean;
}

export interface BatchRunInfo {
  id: string;
  trigger: "schedule" | "manual";
  status: "running" | "ok" | "error" | "skipped";
  processed: number;
  candidates: number;
  error: string | null;
  cursorFrom: string | null;
  cursorTo: string | null;
  startedAt: string;
  finishedAt: string | null;
}

export interface RecordsPayload {
  records: TeamRecordItem[];
  runs: BatchRunInfo[];
  nextRunAt: string;
  offHour?: string;
  run?: BatchRunInfo;
  taskId?: string | null;
}

export interface BriefingRecord {
  id: string;
  type: string;
  typeKo: string;
  text: string;
  author: string;
  quote: string;
  at: string;
}

export interface Briefing {
  since: string | null;
  pendingRecords: BriefingRecord[];
  newRecords: BriefingRecord[];
  mentions: { id: string; author: string; text: string; at: string }[];
  myTasks: { id: string; title: string; due: string; status: string }[];
  reviews: { id: string; docLabel: string; by: string; counts: Record<string, number> }[];
  documents: { id: string; label: string; by: string }[];
  reports: { id: string; title: string; by: string; written: number }[];
  lastRun: BatchRunInfo | null;
}

// ─── 마이페이지(워크스페이스 홈) — BE mypage.py ───
export interface MyTodo {
  id: string;
  title: string;
  /** YYYY-MM-DD, 없으면 "" */
  due: string;
  start: string;
  status: TaskItem["status"];
  done: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface MyReviewRequest {
  taskId: string;
  reportId: string;
  title: string;
  /** 받은 요청 = 요청한 사람, 보낸 요청 = 검토자 */
  person: string;
  done: boolean;
  at: string;
  updatedAt: string;
  /** 요청 메모 */
  note?: string;
}

export interface MyDocument {
  id: string;
  title: string;
  reportType: string;
  written: number;
  sections: number;
  updatedAt: string;
  review: { person: string; done: boolean } | null;
}

export interface MyActivity {
  kind: "write" | "upload" | "review" | "request" | "done";
  title: string;
  at: string;
  person?: string;
  reportId?: string;
}

export interface MyPage {
  me: { id: string; name: string; title: string; role: Role };
  todos: MyTodo[];
  received: MyReviewRequest[];
  sent: MyReviewRequest[];
  documents: MyDocument[];
  activity: MyActivity[];
  reviewers: { id: string; name: string }[];
}

/** 알림함 — backend app/notify.py view(). link = 화면 이동(?w=&v=&s=&t=) */
export interface NotificationItem {
  id: string;
  workspaceId: string;
  kind: "routine" | "share" | "review" | "assumption" | "source" | "dashboard" | "calendar" | "proposal" | "criteria" | "system";
  title: string;
  body: string;
  link: { w?: string; v?: string; s?: string; t?: string };
  ref: Record<string, unknown>;
  createdAt: string;
  read: boolean;
}
