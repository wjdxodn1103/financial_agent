/** 화면 문구 상수 — 서버 stage·도구 이름 → 사용자 문구(OP-FE constants.ts 의 STATUS_* 자리. 한국어 단일 언어라 i18n 사전 대신 여기 둔다). */
import type { ApprovalKind, NumberStatus } from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8200").replace(/\/$/, "");
export const STORAGE_PREFIX = "evidesk";

const STAGES: Record<string, string> = {
  route: "요청을 살피는 중",
  think: "생각하는 중",
  respond: "답하는 중",
  wrapup: "정리하는 중",
  "writer.retrieve": "자료에서 근거를 찾는 중",
  "writer.generate": "섹션을 쓰는 중",
  "writer.search": "작성 중 자료를 더 찾는 중",
  "writer.calc": "원장 수치로 계산하는 중",
  "writer.cite": "출처를 정리하는 중",
};

const TOOLS: Record<string, string> = {
  search_documents: "자료 검색",
  list_documents: "자료 목록 확인",
  lookup_figures: "근거 원장에서 수치 찾기",
  calculate: "원장 수치로 계산",
  fetch_dart: "DART 재무제표 가져오기",
  get_progress: "진행 상황 확인",
  set_report_meta: "리포트 설정 저장",
  write_section: "섹션 작성",
  revise_section: "섹션 수정",
  propose_plan: "작성 순서 제안",
  continue_plan: "작성 순서 진행",
  update_outline: "목차 편집",
  build_table: "표 만들기",
  update_table: "표 고치기",
  save_template: "양식 저장",
  save_table_to_drive: "드라이브에 저장",
};

export function statusLabel(stage: string | null | undefined): string | null {
  if (!stage) return null;
  if (stage.startsWith("tool:")) return TOOLS[stage.slice(5)] ?? "작업하는 중";
  return STAGES[stage] ?? null;
}

export function toolLabel(name: string): string {
  return TOOLS[name] ?? name;
}

/** 원본 칸·계산식에 이어진 숫자 판정 — 본문 밑줄과 숫자 출처 탭이 같이 쓴다(나머지 판정은 화면에 따로 표시하지 않는다) */
export const LINKED_NUMBER: ReadonlySet<NumberStatus> = new Set<NumberStatus>(["source", "calc"]);

export const CARD_KIND_LABEL: Record<ApprovalKind, string> = {
  write: "섹션 작성",
  rewrite: "다시 작성",
  new: "새 섹션",
  revise: "섹션 수정",
  plan: "계획 작성",
};

export const ERROR_TEXT: Record<string, string> = {
  NO_PROVIDER: "NVIDIA API 키가 설정되지 않았습니다. backend/.env 의 NVIDIA_API_KEY 를 확인해 주세요.",
  SESSION_BUSY: "이 리포트에서 아직 앞선 요청을 처리하고 있습니다. 잠시 뒤 다시 보내 주세요.",
  RATE_LIMITED: "요청이 몰려 잠시 기다려야 합니다.",
  PROVIDER_AUTH: "모델 서버 인증에 실패했습니다.",
  PROVIDER_UNREACHABLE: "모델 서버와 연결이 끊겼습니다. 같은 내용을 다시 보내 주세요.",
  EMPTY: "보낼 내용이 없습니다.",
};
