/**
 * BE(/api) 계약 타입 — backend/app 의 응답 모양 그대로(camelCase).
 * OP-FE features/paper/types.ts 에서 리포트에 필요한 것만 남기고 이름을 바꿨다(paper → report, reference → document).
 */

// ─── 메타 ───
/** 기본 유형(equity·industry·peer·memo) + 고정 양식 id(BE app/formats, 예: nbim_half_year) */
export type ReportTypeId = string;

export interface InputField {
  key: string;
  label: string;
  placeholder?: string;
  multiline?: boolean;
}

export interface TemplateItem {
  id: string;
  title: string;
  phase: "front" | "body" | "back";
  level: "required" | "recommended";
  desc: string;
  inputs: InputField[];
  /** 고정 양식 — 이 섹션 뒤에 붙는 표·그림 */
  blocks?: { id: string; kind: "table" | "chart"; no: number; label: string }[];
}

export interface ReportTypeInfo {
  id: ReportTypeId;
  title: string;
  desc: string;
  items: TemplateItem[];
  order: string[];
  /** type = 기본 유형, format = 표·그림 블록이 딸린 고정 양식, free = 양식 없음(대화만 하는 작업의 기본), registered = 샘플에서 등록한 양식(rt:) */
  kind?: "type" | "format" | "free" | "registered";
  /** 등록 양식 — 범위·만든 사람 */
  scope?: "company" | "workspace" | "user";
  owner?: string;
  ownerId?: string;
  tags?: string[];
  sample?: string;
  dataNote?: string;
  tables?: number;
  charts?: number;
}

export interface ProviderInfo {
  kind: "nvidia" | "none";
  model: string;
  writer: string;
  embed: string;
}

export interface UserInfo {
  id: string;
  name: string;
  title: string;
}

export type Role = "owner" | "editor" | "reviewer" | "viewer";

export interface WorkspaceKind {
  id: string;
  title: string;
  desc: string;
  reportType: ReportTypeId;
}

export interface Meta {
  reportTypes: ReportTypeInfo[];
  defaultType: ReportTypeId;
  provider: ProviderInfo;
  workspaceKinds: WorkspaceKind[];
  roles: { id: Role; label: string }[];
  users: UserInfo[];
  connectors: { dart: boolean; edgar: boolean; ecos: boolean };
}

// ─── 세션 ───
export interface SessionSetup {
  title: string;
  subject: string;
  asOf: string;
  audience: string;
}

export interface ReportSection {
  step: string;
  title: string;
  status: "empty" | "written";
  covers: string[];
  content?: string;
  /** 등록한 DOCX 양식의 안내문 */
  guide?: string;
}

export interface SectionChecks {
  citations: number;
  documents: number;
  searchCalls: number;
  presearch: number;
  removedSources: number;
  unsourcedNumbers: string[];
  /** 출처를 달았지만 인용한 자료·근거 원장·계산 어디에도 없는 숫자 */
  mismatchedNumbers?: string[];
  numbersChecked?: number;
  numbersMatched?: number;
  ledgerShown?: number;
  calcs?: number;
  truncated: boolean;
}

/** 코드가 계산한 파생 수치(calculate 도구) */
export interface CalcRecord {
  label: string;
  expression: string;
  readable: string;
  value: number;
  display: string;
  percent: boolean;
  inputs: string[];
}

export interface TeamNote {
  typeKo: string;
  text: string;
  author: string;
  quote: string;
  at: string;
}

export interface PublicSession {
  id: string;
  createdAt: string;
  updatedAt: string;
  reportType: ReportTypeId;
  setup: SessionSetup;
  sections: ReportSection[];
  evidence: Record<string, { docIds: string[]; checks?: SectionChecks; warnings?: string[]; calcs?: CalcRecord[] }>;
  template?: { name: string; sections: number; uploadedAt: string } | null;
  transcript: ChatMessage[];
  userInputs: Record<string, string>;
  documentIds: string[];
  /** 이 작업 채팅에서 끈 데이터 id */
  dataExcluded?: string[];
  /** 참고 데이터 범위(저장된 값) */
  dataScope?: DataScope;
  lastWrittenStep?: string | null;
  /** AI 작업 — 오른쪽 '결과'에서 마지막으로 본 표 */
  currentTableId?: string | null;
}

export interface SessionListItem {
  id: string;
  title: string;
  reportType: ReportTypeId;
  written: number;
  sections: number;
  createdBy: string;
  updatedAt?: string;
  /** 문서가 붙은 작업인가(아니면 대화만) */
  hasDoc?: boolean;
  /** 아직 아무것도 안 한 작업(대화·문서 없음) */
  empty?: boolean;
}

// ─── 리포트 뷰(BE 가 조립, FE 는 그리기만) ───
export interface CiteAnchor {
  docId: string;
  chunk: string;
  n: number;
}

export interface CitationSpan {
  start: number;
  end: number;
  anchors: CiteAnchor[];
  sentence: string;
}

export type ReportBlock =
  | { kind: "heading"; step: string; text: string; status: "written" | "empty" }
  | { kind: "para"; step: string; text: string; cites: CitationSpan[] }
  | { kind: "list"; step: string; items: { text: string; cites: CitationSpan[] }[] }
  | { kind: "empty"; step: string; title: string; desc: string; slots?: { kind: "table" | "chart" | "figure"; title: string }[] }
  | TableBlock
  | ChartBlock;

/** 고정 양식 블록 공통(BE app/formats/blocks.py) — 숫자는 코드가 데이터 워크북에서 옮긴다 */
interface FormatBlockBase {
  step: string;
  blockId: string;
  no: number;
  label: string;
  title: string;
  unit: string;
  number: string;
  sheet?: string;
  missing: boolean;
  docId?: string;
  docLabel?: string;
  chunk?: string;
  /** 참고 자료 번호 [n] */
  sourceNo?: number;
  /** AI 채팅 표(BE research/block.py) — 캡션·출처 줄(여러 자료) */
  caption?: string;
  sourceLine?: string;
  sourceDocIds?: string[];
  /** 섹션에 넣은 AI 채팅 표의 자리 id — 빼기에 쓴다 */
  insertedId?: string;
  /** 문서 양식의 표·차트 양식으로 만든 것(BE research/forms.py) — 겉모양과 양식 이름 */
  look?: FormLook;
  formName?: string;
}

/** 문서 양식의 표·차트 양식 겉모양(BE templates_import/forms.py look) */
export interface FormLook {
  headerFill?: string;
  headerText?: string;
  rule?: string;
  lines?: "horizontal" | "grid" | "none";
  numberAlign?: "right" | "center" | "left";
  colors?: string[];
  grid?: boolean;
  labels?: boolean;
  captionBold?: boolean;
  captionColor?: string;
}

/** 문서 화면의 '표·차트 넣기' 목록 — 이 문서 양식의 표·차트 양식(BE report/view.py forms) */
export interface ReportForm {
  id: string;
  kind: "table" | "chart";
  name: string;
  desc: string;
  chartType: string;
}

export interface TableCell {
  text: string;
  num: boolean;
  /** 근거 원장 figure id(doc:chunk.r.c) — 이 칸이 옮겨 온 데이터 칸 */
  fid?: string;
  chunk?: string;
  cell?: [number, number];
  /** 칸마다 자료가 다른 표(AI 채팅 표) — 없으면 블록의 docId */
  docId?: string;
  /** 글 칸의 인용 문단 */
  cites?: { docId: string; chunk: string; label: string; page?: number | null }[];
  /** 툴팁 — 출처·계산식·빈 칸 이유 */
  title?: string;
  kind?: "number" | "text" | "calc" | "empty" | "head";
}

export interface TableBlock extends FormatBlockBase {
  kind: "table";
  header: string[];
  rows: TableCell[][];
  /** 양식 표의 묶음 머리 줄 — 첫 열 뒤 열들을 span 만큼(group = 묶음, 아니면 두 줄을 합친 칸) */
  headGroups?: { label: string; span: number; group?: boolean }[];
}

/** 리서치 메모(에셋 kind=note) — 답 그대로, 출처는 [문서, p.n](#cite=문서~문단) 링크 */
export interface NoteBlock {
  kind: "note";
  blockId: string;
  title: string;
  text: string;
  cites: { docId: string; chunk: string; label: string }[];
  missing: boolean;
}

/** 리서치 차트의 점 — 원 표 칸(누르면 원문) */
export interface ChartPoint {
  kind?: string;
  text?: string;
  title?: string;
  fid?: string;
  docId?: string;
  chunk?: string;
  cell?: [number, number] | null;
}

export interface ChartBlock extends FormatBlockBase {
  kind: "chart";
  categories: string[];
  /** type·axis = 막대+선(combo)의 계열별 모양·오른쪽 축, computed = 밴드의 계산 띠선(점 없음) */
  series: { name: string; values: (number | null)[]; type?: "bar" | "line" | "area"; axis?: "right"; computed?: boolean }[];
  horizontal: boolean;
  from?: string;
  /** bar(기본) | line | area | pie | combo | band — 리서치 차트(BE research/chart.py) */
  chartType?: "bar" | "line" | "area" | "pie" | "combo" | "band";
  /** 오른쪽 축 단위(combo) */
  unit2?: string;
  /** 범례 자리(양식) — top | bottom | right | none */
  legend?: string;
  /** 점마다 원 칸 — [계열][범주] */
  points?: (ChartPoint | null)[][];
}

export interface ReportSource {
  n: number;
  docId: string;
  label: string;
  docType: string;
  date: string;
  issuer: string;
  fileName: string;
  missing?: boolean;
}

export interface ProgressEntry {
  item: { id: string; title: string; phase: string; level: "required" | "recommended"; desc: string };
  covered: boolean;
  by: { step: string; title: string }[];
}

export interface ReportView {
  title: string;
  subtitle: string;
  blocks: ReportBlock[];
  sources: ReportSource[];
  progress: ProgressEntry[];
  stats: { sections: number; written: number; chars: number; citations: number; documents: number; required: number; requiredCovered: number };
  /** 이 문서 양식의 표·차트 양식(샘플로 만든 양식만) */
  forms?: ReportForm[];
}

// ─── 검토 준비 (BE app/report/readiness.py) ───
export type ReadinessKind = "unwritten" | "conflict" | "stale" | "mismatch" | "unsourced" | "wrongcite" | "truncated";
export interface ConflictDocRef {
  figureId: string;
  docId: string;
  label: string;
  chunk: string;
  page: number | null;
  sheet: string | null;
  cell: [number, number] | null;
}
/** 섹션 본문 숫자가 가리키는 원장 묶음 중 미해결 충돌 — 자료별 값·출처 → 채택 */
export interface ConflictCard {
  key: string;
  metric: string;
  period: string;
  basis: string | null;
  values: { figureId: string; display: string; docs: ConflictDocRef[] }[];
  quotes: string[];
}
/** 채택값이 있는데 본문 숫자가 다름(채택 뒤 다시 쓰지 않음) */
export interface StaleFlag {
  key: string;
  metric: string;
  period: string;
  written: string;
  chosen: string;
  quote: string;
}
export interface ReviewRequest {
  reviewerId: string;
  requestedBy: string;
  requestedAt: string;
  taskId: string;
  note: string;
  summary: string;
  state: string;
  taskStatus: "todo" | "doing" | "review" | "done" | null;
}
export interface Readiness {
  state: "empty" | "writing" | "attention" | "ready";
  counts: Record<ReadinessKind, number>;
  issues: number;
  sections: number;
  written: number;
  items: { kind: ReadinessKind; step: string; title: string; text: string; key?: string }[];
  flags: Record<string, { conflicts: ConflictCard[]; stale: StaleFlag[] }>;
  kindKo: Record<ReadinessKind, string>;
  reviewRequest: ReviewRequest | null;
  canChoose: boolean;
  canRequest: boolean;
  numbers?: NumberSummary;
}

// ─── 숫자별 확인 (BE app/report/number_check.py) ───
export type NumberStatus = "source" | "calc" | "input" | "mismatch" | "unsourced";
export type NumberFlag = "notCited" | "conflict" | "notChosen";
/** 리포트 뷰 블록 안 숫자 위치 — b = blocks 번호, i = 목록 항목 번호(문단이면 null). 위치는 렌더된 글 기준 */
export interface NumberSpan {
  b: number;
  i: number | null;
  start: number;
  end: number;
  raw: string;
  key: string;
  status: NumberStatus;
  needsReview: boolean;
  confirmed: boolean;
}
export interface NumberSourceRef {
  via: "cited-cell" | "cited-text" | "ledger" | "calc-input";
  docId: string;
  label: string;
  chunk: string;
  page: number | null;
  sheet: string | null;
  cell: [number, number] | null;
  display: string;
  quote: string;
  column: string;
  metric: string;
  period: string;
}
export interface NumberItem {
  key: string;
  step: string;
  section: string;
  raw: string;
  sentence: string;
  cited: { docId: string; chunk: string }[];
  status: NumberStatus;
  flags: NumberFlag[];
  source?: NumberSourceRef;
  group?: { values: string[]; chosen: string | null; key: string } | null;
  calc?: { label: string; readable: string; display: string; inputs: NumberSourceRef[] };
  needsReview: boolean;
  confirmed: { by: string; byName: string; at: string; note: string; status: NumberStatus } | null;
}
export interface NumberSummary {
  total: number;
  byStatus: Record<NumberStatus, number>;
  auto: number;
  needsReview: number;
  reviewConfirmed: number;
  confirmed: number;
}
export interface NumberReport {
  spans: NumberSpan[];
  items: Record<string, NumberItem>;
  order: string[];
  summary: NumberSummary;
  statusKo: Record<NumberStatus, string>;
  flagKo: Record<NumberFlag, string>;
  canConfirm: boolean;
}

// ─── 자료 ───
/** 워크스페이스 안 판 묶음(BE app/docs/versions.py) — 활성 판만 목록에, 이전 판은 보관 */
export interface DocVersionInfo {
  version: number;
  prevId: string | null;
  history: { docId: string; version: number; label: string; fileName: string; at: string }[];
}
export interface VersionRef {
  docId: string;
  chunk: string;
  cell: [number, number] | null;
  page: number | null;
  sheet: string | null;
  display: string;
}
export interface VersionCompareResult {
  old: { docId: string; label: string };
  new: { docId: string; label: string };
  changed: { metric: string; period: string; basis: string | null; before: VersionRef; after: VersionRef; delta: number; percent: boolean }[];
  added: { metric: string; period: string; basis: string | null; after: VersionRef }[];
  removed: { metric: string; period: string; basis: string | null; before: VersionRef }[];
  same: number;
}

export interface DocumentCard {
  id: string;
  /** 드라이브 — 자료 속 표 수·이 자료로 만든 에셋·비슷한 문서에서 만든 같은 모양 표 */
  assets?: { tables: number; same: number; similar: number } | null;
  uploadedBy?: string;
  version?: DocVersionInfo | null;
  /** 공용 자료실에 올라가 있으면 */
  library?: { id: string; publishedBy: string } | null;
  /** 이 워크스페이스에서 AI 가 참고하지 않음(검수 대상 초안은 검수 시작 때 자동) */
  excluded?: boolean;
  /** 사내 공용 데이터(모든 워크스페이스 기본) */
  shared?: boolean;
  /** 이 작업 채팅에서 끈 데이터(리포트 화면) */
  off?: boolean;
  /** 이 워크스페이스(사내 것은 사내 목록)에 올라온 시각 */
  uploadedAt?: string | null;
  /** 원본 파일 크기(바이트) */
  size?: number;
  label: string;
  title: string;
  docType: string;
  date: string;
  issuer: string;
  company: string;
  oneLine: string;
  fileName: string;
  fileType: string;
  pageCount: number | null;
  chunkCount: number;
  paragraphCount: number;
  embedded: boolean;
  enriched: boolean;
  enriching?: boolean;
  createdAt?: string;
  /** 데이터 연결로 가져온 스냅샷 — 조회 시각·원본 주소 */
  snapshot?: { connector: string; title: string; fetchedAt: string; url: string } | null;
}

export interface IngestJob {
  id: string;
  fileName: string;
  status: "queued" | "processing" | "done" | "error";
  error?: string;
  docId?: string;
  createdAt?: string;
}

export interface DocumentsPayload {
  documents: DocumentCard[];
  jobs: IngestJob[];
  errors?: string[];
}

export interface DocChunk {
  id: string;
  text: string;
  page: number | null;
  kind: "prose" | "table";
  heading?: string;
  index?: number;
  /** 표의 칸 구조(첫 행 = 머리글) — 원장 figure 의 cell 이 이 좌표를 가리킨다 */
  rows?: string[][];
  /** XLSX 시트 이름 */
  sheet?: string;
}

export interface ChunksPage {
  docId: string;
  total: number;
  offset: number;
  chunks: DocChunk[];
}

export interface ChunkContext {
  docId: string;
  label: string;
  fileName: string;
  chunk: DocChunk;
  prev: DocChunk | null;
  next: DocChunk | null;
  total: number;
}

export interface SessionPayload {
  session: PublicSession;
  report: ReportView;
  suggestions: string[];
  provider: ProviderInfo;
  documents: DocumentCard[];
  /** 참고 데이터 범위 — default(워크스페이스 기본값) | custom(고른 데이터·폴더) */
  dataScope?: DataScopeView;
  workspaceId: string;
  owner: UserInfo;
  /** 에이전트 대화는 작성자만(대화는 개인, 기록은 공유) */
  canChat: boolean;
  /** AI 작업 — 켜진 모드, 문서가 붙어 있나, 이 작업의 표·차트 */
  modes?: Modes;
  /** 문서 판(중간 저장) — 최근 것 먼저 */
  versions?: DocVersion[];
  hasDoc?: boolean;
  tables?: import("../research/types").ResearchTable[];
}

/** 새 문서·작업 채팅의 참고 데이터 — 보낼 때 */
/** 데이터 묶음 — 워크스페이스 데이터 · 사내 데이터 · 개인 데이터(내가 만든 '나만' 폴더 속) */
export type DataGroup = "workspace" | "company" | "personal";

/** 참고 데이터 범위 — 데이터 설정은 groups + docIds, 새 문서 창은 옛 모양(mode: default | custom + docIds·folderIds) */
export interface DataScope {
  mode?: "default" | "custom";
  groups?: Record<DataGroup, boolean>;
  docIds?: string[];
  folderIds?: string[];
}

/** 참고 데이터 — 화면에 보일 때(이름 포함). groups·counts = 데이터 설정 버튼(켬·끔, 묶음마다 데이터 수) */
export interface DataScopeView {
  mode: "default" | "custom";
  groups?: Record<DataGroup, boolean>;
  counts?: Record<DataGroup, number>;
  docs: { id: string; label: string; group?: DataGroup | null }[];
  folders: { id: string; name: string }[];
}

// ─── 채팅 ───
export interface ToolRun {
  id: string;
  name: string;
  args?: Record<string, string>;
  status: "running" | "done" | "error";
  summary?: string;
}

export type ApprovalKind = "write" | "rewrite" | "new" | "revise" | "plan";

export interface ApprovalDoc {
  id: string;
  label: string;
  docType: string;
  embedded: boolean;
}

export interface Approval {
  question: string;
  action: "plan" | "revise";
  kind?: ApprovalKind;
  steps: string[];
  options?: { id: string; label: string; count: number }[];
  covers?: string[];
  instruction?: string;
  documents?: ApprovalDoc[];
  itemDesc?: string;
  inputFields?: InputField[];
  inputs?: Record<string, string>;
  note?: string;
  /** 이 섹션과 관련된 확정 팀 기록 */
  notes?: TeamNote[];
  state: "pending" | "approved" | "rejected";
  chosen?: string;
  /** 화면 전용 — 카드에서 뺀 자료 */
  excludedDocs?: string[];
}

export interface PlanCardData {
  items: string[];
  done: number;
  note?: string;
  proposed?: boolean;
  resolved?: boolean;
}

export interface SectionUpdate {
  step: string;
  title: string;
  chars: number;
  checks?: SectionChecks;
  warnings?: string[];
  covers?: string[];
  /** 이 화면에서 받은 카드만 되돌리기 가능(새로고침 뒤에는 이전 본문을 모른다) */
  revertable?: boolean;
  undone?: boolean;
}

export interface StreamError {
  code?: string;
  message: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  tools?: ToolRun[];
  approval?: Approval;
  plan?: PlanCardData;
  sectionUpdates?: SectionUpdate[];
  /** 이 답에서 만든·고친 리서치 표·차트(결과 카드) */
  tables?: { id: string; title: string }[];
  /** AI 가 찾아서 연 문서(R)·데이터 파일(F) — 여는 버튼 */
  links?: ItemLink[];
  /** 양식 샘플 카드 — 표·차트 하나씩 + 리포트 양식 */
  imports?: ImportBox;
  /** 사용자 메시지에 붙은 파일 이름(양식 샘플) */
  attachment?: string;
  error?: StreamError;
  streaming?: boolean;
  aborted?: boolean;
  status?: string;
}

export interface ApprovalBody {
  approved: boolean;
  action: string;
  messageId: string;
  steps: string[];
  covers?: string[];
  documents?: string[];
  instruction?: string;
  inputs?: Record<string, string>;
  label?: string;
}

/** 양식 샘플(BE templates_import) — 표·차트 카드(하나씩 등록·건너뛰기)와 리포트 양식 카드(한꺼번에) */
export interface ImportCard {
  n: number;
  kind: "table" | "chart";
  title: string;
  section: string | null;
  spec: import("../research/types").TemplateSpec & { chart?: { type: "bar" | "line"; horizontal: boolean; seriesLabels: string[] } };
  via: "llm" | "rule" | "vl";
  block: TableBlock | ChartBlock;
  sampleRows: string[];
  state: "pending" | "registered" | "skipped";
  templateId?: string;
  scope?: "company" | "workspace" | "user";
}
export interface ImportFormat {
  name: string;
  sections: { title: string; level: number; guide: string; assets: number[]; figures: string[] }[];
  state: "pending" | "registered";
  reportType?: string;
  scope?: "company" | "workspace" | "user";
}
export interface ImportBox {
  id: string;
  items: ImportCard[];
  format: ImportFormat | null;
}

/** 찾아서 연 것 — doc = 문서(AI 작업), file = 데이터 파일 */
export interface ItemLink {
  kind: "doc" | "file";
  id: string;
  title: string;
}

export interface DocVersion {
  id: string;
  at: string;
  label: string;
  written: number;
}

/** AI 작업 모드 — 하나씩(둘 다 거짓 = 일반 대화) */
export interface Modes {
  research: boolean;
  writing: boolean;
}

export type ChatTurnBody = { text: string; modes?: Modes; tableId?: string | null } | { approval: ApprovalBody } | { import: string };

export type StreamEvent =
  | { type: "meta"; sessionId?: string; model?: string }
  | { type: "status"; stage: string }
  | { type: "thinking"; delta: string }
  | { type: "text"; delta: string }
  | { type: "text_replace"; text: string }
  | { type: "tool_start"; id: string; name: string; args?: Record<string, string> }
  | { type: "tool_end"; id: string; name: string; status: "done" | "error"; summary?: string }
  | { type: "section_update"; step: string; title: string; chars: number; content: string; covers?: string[]; checks?: SectionChecks; warnings?: string[]; sections: ReportSection[]; report?: ReportView }
  | { type: "outline_update"; sections: ReportSection[]; report?: ReportView }
  | { type: "setup_update"; setup: SessionSetup; report?: ReportView }
  | ({ type: "approval" } & Omit<Approval, "state">)
  | { type: "plan_update"; items: string[]; done: number; note?: string; proposed?: boolean }
  | { type: "suggestions"; chips: string[] }
  | { type: "table_update"; table: import("../research/types").ResearchTable }
  | { type: "template_saved"; template: import("../research/types").ResearchTemplate }
  | { type: "item_link"; item: ItemLink }
  | { type: "import_item"; importId: string; item: ImportCard }
  | { type: "import_format"; importId: string; format: ImportFormat }
  | { type: "error"; message: string; code?: string }
  | { type: "done" };
