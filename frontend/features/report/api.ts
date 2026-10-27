/**
 * BE REST 호출(fetch). SSE 는 stream.ts. 오류는 ApiError 로 throw — 호출자가 status 로 가른다.
 * 모든 요청에 로그인 계정(`X-User-Id`)을 싣는다. 자료는 워크스페이스에 붙는다(`/workspaces/{w}/documents`).
 */
import { authHeaders, getUserId } from "../workspace/auth";
import { API_BASE } from "./constants";
import type { ChunkContext, ChunksPage, DocumentsPayload, Meta, NumberReport, Readiness, SessionPayload, VersionCompareResult } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}

export async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers: { ...authHeaders(), ...(init?.headers ?? {}) } });
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    let code: string | undefined;
    try {
      const j = await res.json();
      const detail = j.detail && typeof j.detail === "object" ? j.detail : null;
      message = j.message ?? detail?.message ?? j.detail ?? message;
      code = j.code ?? detail?.code;
    } catch {
      /* 본문 없음 */
    }
    throw new ApiError(res.status, String(message), code);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const jsonInit = (method: string, body?: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
const sid = (id: string) => `/api/sessions/${encodeURIComponent(id)}`;
const wid = (id: string) => `/api/workspaces/${encodeURIComponent(id)}`;

export const getMeta = () => req<Meta>("/api/meta");
export const getSession = (id: string) => req<SessionPayload>(sid(id));
/** 시작 화면 추천 카드 4개(BE app/start_cards.py — 내 기록으로 코드가 고른다) */
export interface StartCard {
  id: string;
  kind: string;
  title: string;
  sub: string;
  action:
    | { type: "send"; text: string; modes?: Partial<import("./types").Modes> | null }
    | { type: "open"; reportId: string }
    | { type: "tables"; docId: string; label: string }
    | { type: "view"; view: import("../workspace/types").WorkspaceView }
    /** 그 양식으로 문서 시작 / 양식 고르기 창 */
    | { type: "format"; reportType: string }
    | { type: "pick" };
}
export const getStartCards = (id: string) => req<{ cards: StartCard[] }>(`${sid(id)}/start-cards`);
export const deleteSession = (id: string) => req<void>(sid(id), { method: "DELETE" });
/** 화면 편집 — 한 번에 한 가지: {step, content} / {step, title} / {order} / {remove} / {setup} / {reportType} */
export const patchSession = (id: string, body: Record<string, unknown>) => req<SessionPayload>(sid(id), jsonInit("PATCH", body));
/** 진행 중인 턴을 서버에서 바로 끊는다(중단 버튼이 스트림 abort 와 같이 부른다) */
export const cancelTurn = (id: string) => req<{ cancelled: boolean }>(`${sid(id)}/cancel`, { method: "POST" });

// ─── 검토 준비 ───
export const getReadiness = (id: string) => req<Readiness>(`${sid(id)}/readiness`);
/** 작성자 → 검토자 작업 항목 + 채널 알림(확인할 것이 남아 있어도 막지 않고 요약에 적는다) */
export const requestReview = (id: string, reviewerId: string, note = "") => req<Readiness>(`${sid(id)}/review-request`, jsonInit("POST", { reviewerId, note }));

// ─── 숫자별 확인 ───
export const getNumbers = (id: string) => req<NumberReport>(`${sid(id)}/numbers`);
/** 사람 확인 표시(검토자 이상) — confirmed=false 면 취소 */
export const confirmNumber = (id: string, key: string, confirmed: boolean, note = "", raw = "") =>
  req<NumberReport>(`${sid(id)}/numbers/${encodeURIComponent(key)}`, jsonInit("POST", { confirmed, note, raw }));

// ─── DOCX 양식 ───
export const uploadTemplate = (id: string, file: File) => {
  const fd = new FormData();
  fd.append("file", file, file.name);
  return req<SessionPayload>(`${sid(id)}/template`, { method: "POST", body: fd });
};
export const removeTemplate = (id: string) => req<SessionPayload>(`${sid(id)}/template`, { method: "DELETE" });

// ─── 자료(워크스페이스) ───
export const getDocuments = (w: string) => req<DocumentsPayload>(`${wid(w)}/documents`);
/** replaces = 이 자료의 새 판(파일 하나) — 처리가 끝나면 이전 판 자리를 차지하고 이전 판은 보관된다 */
export const uploadDocuments = (w: string, files: File[], replaces?: string, folder?: string | null) => {
  const fd = new FormData();
  for (const f of files) fd.append("files", f, f.name);
  if (replaces) fd.append("replaces", replaces);
  if (folder) fd.append("folder", folder);
  return req<DocumentsPayload>(`${wid(w)}/documents`, { method: "POST", body: fd });
};
/** 같은 자료의 두 판 표 칸 숫자 비교(other 가 없으면 바로 앞 판과) */
export const compareVersions = (w: string, docId: string, other?: string) =>
  req<VersionCompareResult>(`${wid(w)}/documents/${docId}/compare${other ? `?with=${encodeURIComponent(other)}` : ""}`);
export const removeDocument = (w: string, params: { job?: string; doc?: string }) =>
  req<DocumentsPayload>(`${wid(w)}/documents?${new URLSearchParams(params as Record<string, string>)}`, { method: "DELETE" });
/** 문단 페이지 — 뷰어가 스크롤하며 불러온다 */
export const getChunks = (w: string, docId: string, offset: number, limit = 30) => req<ChunksPage>(`${wid(w)}/documents/${docId}/chunks?offset=${offset}&limit=${limit}`);
/** 근거 문단(앞뒤 포함) */
export const getChunk = (w: string, docId: string, chunkId: string) => req<ChunkContext>(`${wid(w)}/documents/${docId}/chunk?id=${encodeURIComponent(chunkId)}`);
/** 링크로 여는 원본 — 헤더를 못 실어 계정을 쿼리로 */
/** 원문 확인 — 가공한 값이 원본 파일의 어디인지(BE app/docs/source_view.py) */
export type SourceLocation = {
  docId: string;
  label: string;
  fileName: string;
  found: boolean;
  where: string;
  extracted: { display?: string; metric?: string; period?: string; raw?: string } | { text: string } | null;
} & (
  /** marks = 쪽마다 상자(문단이 다음 쪽으로 이어지면 쪽이 둘 이상) — 없으면 rects 가 page 쪽 상자 */
  | { kind: "pdf"; page: number; pages: number; ratio: number; rects: [number, number, number, number][]; marks?: Record<string, [number, number, number, number][]> }
  | { kind: "sheet"; sheet: string; cols: string[]; rowNums: number[]; grid: string[][]; hl: [number, number][] }
  | { kind: "docx"; blocks: ({ type: "p"; text: string } | { type: "table"; rows: string[][] })[]; at: number | null; cell: [number, number] | null }
  | { kind: "text"; lines: string[]; lineNums: number[]; hl: number[]; mark: string }
);
export const locateSource = (w: string, docId: string, chunk?: string | null, cell?: [number, number] | null) => {
  const p = new URLSearchParams();
  if (chunk) p.set("chunk", chunk);
  if (cell) p.set("cell", `${cell[0]},${cell[1]}`);
  return req<SourceLocation>(`${wid(w)}/documents/${encodeURIComponent(docId)}/locate?${p}`);
};
export const pageImageUrl = (w: string, docId: string, page: number) => `${API_BASE}${wid(w)}/documents/${encodeURIComponent(docId)}/page/${page}.png?uid=${encodeURIComponent(getUserId() ?? "")}`;
export const documentFileUrl = (w: string, docId: string) => `${API_BASE}${wid(w)}/documents/${docId}/file?uid=${encodeURIComponent(getUserId() ?? "")}`;

// ─── 내보내기 ───
function fileNameFrom(header: string | null, fallback: string): string {
  const star = header && /filename\*=(?:UTF-8|utf-8)''([^;]+)/.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      /* 폴백 */
    }
  }
  return fallback;
}

/** 인증 헤더를 실어 파일을 받아 저장한다(DOCX·XLSX 공통) */
export async function downloadFile(path: string, fallback: string, init?: RequestInit): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers: { ...authHeaders(), ...(init?.headers ?? {}) } });
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileNameFrom(res.headers.get("content-disposition"), fallback);
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const downloadDocx = (id: string) => downloadFile(`${sid(id)}/export`, "report.docx");
/** 고정 양식 리포트의 표·그림 데이터(블록마다 시트 + 엑셀 막대 그래프) */
export const downloadBlocksXlsx = (id: string) => downloadFile(`${sid(id)}/export.xlsx`, "tables.xlsx");
