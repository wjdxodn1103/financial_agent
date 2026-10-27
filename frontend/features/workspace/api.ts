/** 워크스페이스 REST — 공통 req(인증 헤더·ApiError)는 report/api 의 것을 쓴다. */
import { downloadFile, jsonInit, req } from "../report/api";
import type { DataScope, DocumentCard, ReportTypeId, Role, SessionListItem, SessionPayload } from "../report/types";
import type {
  Briefing,
  ChannelMsg,
  ConnectorInfo,
  DartCompany,
  DriveListing,
  DriveSearch,
  EcosItem,
  EcosTable,
  EdgarCompany,
  FolderAccess,
  Ledger,
  LibraryEntry,
  MyPage,
  RecordsPayload,
  Review,
  SearchResult,
  TaskItem,
  WorkspaceDetail,
  WorkspaceListItem,
} from "./types";

const wid = (id: string) => `/api/workspaces/${encodeURIComponent(id)}`;

export const listWorkspaces = async () => (await req<{ workspaces: WorkspaceListItem[] }>("/api/workspaces")).workspaces ?? [];
export const createWorkspace = (body: { name: string; kind: string; description?: string }) => req<WorkspaceDetail>("/api/workspaces", jsonInit("POST", body));
export const getWorkspace = (id: string) => req<WorkspaceDetail>(wid(id));
export const patchWorkspace = (id: string, body: Record<string, unknown>) => req<WorkspaceDetail>(wid(id), jsonInit("PATCH", body));

export const inviteMember = (id: string, userId: string, role: Role) => req<WorkspaceDetail>(`${wid(id)}/members`, jsonInit("POST", { userId, role }));
export const setMemberRole = (id: string, userId: string, role: Role) => req<WorkspaceDetail>(`${wid(id)}/members/${userId}`, jsonInit("PATCH", { role }));
export const removeMember = (id: string, userId: string) => req<WorkspaceDetail>(`${wid(id)}/members/${userId}`, { method: "DELETE" });

export const listReports = async (id: string) => (await req<{ reports: SessionListItem[] }>(`${wid(id)}/reports`)).reports ?? [];
export const createReport = (id: string, body: { title?: string; reportType?: ReportTypeId; folderId?: string | null; dataScope?: DataScope }) => req<SessionPayload>(`${wid(id)}/reports`, jsonInit("POST", body));

// 드라이브 — 문서·데이터 폴더
export const getDrive = (id: string, folder?: string | null) => req<DriveListing>(`${wid(id)}/drive${folder ? `?folder=${encodeURIComponent(folder)}` : ""}`);
export const searchDrive = (id: string, q: string) => req<DriveSearch>(`${wid(id)}/drive/search?q=${encodeURIComponent(q)}`);
export const createFolder = (id: string, name: string, parentId?: string | null) => req<DriveListing>(`${wid(id)}/drive/folders`, jsonInit("POST", { name, parentId: parentId ?? null }));
export const updateFolder = (id: string, folderId: string, body: { name?: string; parentId?: string | null; access?: FolderAccess; memberIds?: string[] }) => req<DriveListing>(`${wid(id)}/drive/folders/${folderId}`, jsonInit("PATCH", body));
export const deleteFolder = (id: string, folderId: string) => req<DriveListing>(`${wid(id)}/drive/folders/${folderId}`, { method: "DELETE" });
export const moveDriveItems = (id: string, items: { id: string; kind: "doc" | "data" | "table" }[], folderId: string | null, current: string | null) =>
  req<DriveListing>(`${wid(id)}/drive/move`, jsonInit("POST", { items, folderId, current }));

// 검토 요청 — 작성한 문서 여러 편을 한 검토자에게
export const sendReviewRequests = (id: string, reportIds: string[], reviewerId: string, note = "") => req<{ sent: number }>(`${wid(id)}/review-requests`, jsonInit("POST", { reportIds, reviewerId, note }));

export const getLedger = (id: string) => req<Ledger>(`${wid(id)}/ledger`);
/** 워크스페이스 안 통합 검색(자료 문단·원장·팀 기록·리포트·채널·작업) */
export const searchWorkspace = (id: string, q: string) => req<SearchResult>(`${wid(id)}/search?q=${encodeURIComponent(q)}`);
/** 작업 경과 DOCX — 팀 기록·충돌 채택·검수·자료·작업에서 코드로 묶는다 */
export const downloadProgressDoc = (id: string) => downloadFile(`${wid(id)}/progress-doc`, "progress.docx");
/** 원장 XLSX(원장·충돌·채택·계산 시트 — 계산 결과는 원장 칸을 참조하는 엑셀 수식) */
export const downloadLedgerXlsx = (id: string) => downloadFile(`${wid(id)}/ledger/export`, "ledger.xlsx");
export const chooseLedgerValue = (id: string, key: string, figureId: string, reason = "") => req<Ledger>(`${wid(id)}/ledger/choose`, jsonInit("POST", { key, figureId, reason }));

// ─── 공용 자료실(붙여야 그 워크스페이스에서 쓴다) ───
export const listLibrary = async (q = "", workspaceId?: string) =>
  (await req<{ items: LibraryEntry[] }>(`/api/library?${new URLSearchParams({ q, ...(workspaceId ? { workspace: workspaceId } : {}) })}`)).items ?? [];
export const setDocumentEvidence = (id: string, docId: string, use: boolean) => req<unknown>(`${wid(id)}/documents/${docId}/evidence`, jsonInit("POST", { use }));
export const publishDocument = async (id: string, docId: string, note = "") => (await req<{ items: LibraryEntry[] }>(`${wid(id)}/documents/${docId}/publish`, jsonInit("POST", { note }))).items ?? [];
export const unpublishDocument = async (itemId: string, workspaceId?: string) =>
  (await req<{ items: LibraryEntry[] }>(`/api/library/${itemId}${workspaceId ? `?workspace=${encodeURIComponent(workspaceId)}` : ""}`, { method: "DELETE" })).items ?? [];
export const attachFromLibrary = async (id: string, itemId: string) => (await req<{ items: LibraryEntry[] }>(`${wid(id)}/library/${itemId}/attach`, { method: "POST" })).items ?? [];

export const listConnectors = async (id: string) => (await req<{ connectors: ConnectorInfo[] }>(`${wid(id)}/connectors`)).connectors ?? [];
export const searchDartCompanies = async (id: string, q: string) => (await req<{ companies: DartCompany[] }>(`${wid(id)}/connectors/dart/companies?q=${encodeURIComponent(q)}`)).companies ?? [];
export const fetchDartFinancials = (id: string, body: { corpCode: string; corpName: string; year: number; report: string; fs: string }) =>
  req<{ document: DocumentCard | null; figures: number; title: string }>(`${wid(id)}/connectors/dart/financials`, jsonInit("POST", body));
export const searchEdgarCompanies = async (id: string, q: string) => (await req<{ companies: EdgarCompany[] }>(`${wid(id)}/connectors/edgar/companies?q=${encodeURIComponent(q)}`)).companies ?? [];
export const fetchEdgarFinancials = (id: string, body: { cik: number; name: string; year: number }) =>
  req<{ document: DocumentCard | null; figures: number; title: string }>(`${wid(id)}/connectors/edgar/financials`, jsonInit("POST", body));
export const searchEcosTables = async (id: string, q: string) => (await req<{ tables: EcosTable[] }>(`${wid(id)}/connectors/ecos/tables?q=${encodeURIComponent(q)}`)).tables ?? [];
export const listEcosItems = async (id: string, stat: string) => (await req<{ items: EcosItem[] }>(`${wid(id)}/connectors/ecos/items?stat=${encodeURIComponent(stat)}`)).items ?? [];
export const fetchEcosSeries = (id: string, body: { statCode: string; statName: string; itemCode: string; itemName: string; cycle: string; start: string; end: string }) =>
  req<{ document: DocumentCard | null; figures: number; title: string }>(`${wid(id)}/connectors/ecos/series`, jsonInit("POST", body));

export const listReviews = async (id: string) => (await req<{ reviews: Review[] }>(`${wid(id)}/reviews`)).reviews ?? [];
export const startReview = (id: string, docId: string) => req<Review>(`${wid(id)}/reviews`, jsonInit("POST", { docId }));
export const getReview = (id: string, reviewId: string) => req<Review>(`${wid(id)}/reviews/${reviewId}`);
/** 검수 지적 → Word(대상이 DOCX 면 원본에 메모를 단 사본, 아니면 검수 의견서) */
export const downloadReviewMemo = (id: string, reviewId: string) => downloadFile(`${wid(id)}/reviews/${reviewId}/memo`, "review_memo.docx");
export const makeReviewTasks = (id: string, reviewId: string, findingIds: string[], assigneeId: string | null, due = "") =>
  req<Review & { made: number }>(`${wid(id)}/reviews/${reviewId}/tasks`, jsonInit("POST", { findingIds, assigneeId, due }));

// ─── 채널·팀 기록·브리핑·작업 ───
export const listMessages = (id: string, after?: string) =>
  req<{ messages: ChannelMsg[]; updated: ChannelMsg[] }>(`${wid(id)}/channel${after ? `?after=${encodeURIComponent(after)}` : ""}`);
export const postMessage = (id: string, text: string, attachments: string[] = [], threadId?: string) =>
  req<{ message: ChannelMsg; agent?: ChannelMsg }>(`${wid(id)}/channel`, jsonInit("POST", { text, attachments, threadId }));
export const listRecords = (id: string) => req<RecordsPayload>(`${wid(id)}/records`);
export const addRecord = (id: string, type: string, text: string, scope = "") => req<RecordsPayload>(`${wid(id)}/records`, jsonInit("POST", { type, text, scope }));
export const runRecordsNow = (id: string) => req<RecordsPayload>(`${wid(id)}/records/run`, { method: "POST" });
export const confirmRecord = (id: string, recordId: string, text?: string) => req<RecordsPayload>(`${wid(id)}/records/${recordId}/confirm`, jsonInit("POST", { text }));
export const dismissRecord = (id: string, recordId: string) => req<RecordsPayload>(`${wid(id)}/records/${recordId}/dismiss`, { method: "POST" });
export const getBriefing = (id: string) => req<Briefing>(`${wid(id)}/briefing`);
export const listTasks = async (id: string) => (await req<{ tasks: TaskItem[] }>(`${wid(id)}/tasks`)).tasks ?? [];
export const createTask = (id: string, body: { title: string; detail?: string; assigneeId?: string | null; due?: string; start?: string }) => req<{ tasks: TaskItem[] }>(`${wid(id)}/tasks`, jsonInit("POST", body));
export const updateTask = (id: string, taskId: string, body: Record<string, unknown>) => req<{ tasks: TaskItem[] }>(`${wid(id)}/tasks/${taskId}`, jsonInit("PATCH", body));
export const deleteTask = (id: string, taskId: string) => req<{ tasks: TaskItem[] }>(`${wid(id)}/tasks/${taskId}`, { method: "DELETE" });

// 마이페이지 — 내 할 일·검토 요청·내 문서·내가 한 일
export const getMyPage = (id: string) => req<MyPage>(`${wid(id)}/me`);
export const addMyTodo = (id: string, title: string, due = "", start = "") => req<MyPage>(`${wid(id)}/me/todos`, jsonInit("POST", { title, due, start }));
export const updateMyTask = (id: string, taskId: string, body: { done?: boolean; due?: string; start?: string; title?: string }) => req<MyPage>(`${wid(id)}/me/tasks/${taskId}`, jsonInit("PATCH", body));
export const deleteMyTodo = (id: string, taskId: string) => req<MyPage>(`${wid(id)}/me/todos/${taskId}`, { method: "DELETE" });
