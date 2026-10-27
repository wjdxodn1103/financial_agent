/**
 * 리포트 스튜디오 공유 상태(Jotai) — OP-FE features/paper/store/atoms.ts 의 축소판.
 * 패널 사이에서 같이 보는 것만 atom 으로 둔다(카드 내부 입력 등은 컴포넌트 로컬).
 * report(뷰)는 messages 와 분리해 두어 스트리밍 텍스트 델타가 리포트를 다시 그리지 않게 한다.
 */
import { atom } from "jotai";
import { atomWithStorage } from "jotai/utils";

import { STORAGE_PREFIX } from "./constants";
import type { ResearchTable } from "../research/types";
import type { ChatMessage, DataScopeView, DocumentCard, IngestJob, Meta, Modes, NumberReport, ProviderInfo, PublicSession, Readiness, ReportView, UserInfo } from "./types";

export const metaAtom = atom<Meta | null>(null);
export const sessionAtom = atom<PublicSession | null>(null);
export const reportAtom = atom<ReportView | null>(null);
export const messagesAtom = atom<ChatMessage[]>([]);
/** 검토 준비 점검표·섹션별 충돌 카드 — 리포트 뷰가 바뀔 때마다 다시 받는다 */
export const readinessAtom = atom<Readiness | null>(null);
/** 숫자별 출처 — 본문 숫자마다 원본 칸·계산식(리포트 뷰가 바뀔 때 점검표와 같이 받는다) */
export const numbersAtom = atom<NumberReport | null>(null);
/** 숫자 출처 탭이 펼칠 숫자(본문 숫자를 누르면) */
export const numberFocusAtom = atom<{ key: string; tick: number } | null>(null);
export const suggestionsAtom = atom<string[]>([]);
export const documentsAtom = atom<DocumentCard[]>([]);
/** 이 문서의 참고 데이터 범위(기본값 / 고른 데이터·폴더) */
export const dataScopeAtom = atom<DataScopeView | null>(null);
export const jobsAtom = atom<IngestJob[]>([]);
export const providerAtom = atom<ProviderInfo | null>(null);
/** 에이전트 대화는 리포트 작성자만 — 다른 멤버는 본문·근거만 본다 */
export const canChatAtom = atom<boolean>(false);
export const reportOwnerAtom = atom<UserInfo | null>(null);
export const statusStageAtom = atom<string | null>(null);
export const streamingAtom = atom<boolean>(false);
/** 방금 쓰인·클릭한 섹션 — 리포트 뷰가 잠깐 강조한다 */
export const focusStepAtom = atom<string | null>(null);
/** 진행 맵·빈 섹션 클릭 → 컴포저에 채울 문장(tick 으로 같은 문장도 다시 넣는다) */
export const composerDraftAtom = atom<{ text: string; tick: number }>({ text: "", tick: 0 });
export const loadingAtom = atom<boolean>(true);
export const loadErrorAtom = atom<string | null>(null);
export const uploadingAtom = atom<boolean>(false);
export const exportingAtom = atom<boolean>(false);
/** 뷰어가 여는 문서(+ 그 문서에서 스크롤해 강조할 문단) */
export const viewingDocAtom = atom<{ docId: string; chunk?: string; cell?: [number, number] | null; tick: number } | null>(null);
/** 근거 탭이 펼칠 출처 — 리포트 본문의 [n] 을 누르면 그 문장 */
export interface CitationFocus {
  step: string;
  sentence: string;
  tick: number;
}
export const evidenceFocusAtom = atom<CitationFocus | null>(null);

export const hasUserMessageAtom = atom<boolean>((get) => get(messagesAtom).some((m) => m.role === "user"));

/** AI 작업 모드(리서치·문서 작성) — 턴마다 보내고, 바꾸면 서버에도 저장한다 */
export const modesAtom = atom<Modes>({ research: false, writing: false });
/** 문서 판(중간 저장) */
export const versionsAtom = atom<import("./types").DocVersion[]>([]);
/** 원문 확인 창 — 가공한 값(원장 칸·표 칸·인용 문단)의 원본 위치 */
export const sourceCheckAtom = atom<{ docId: string; chunk?: string | null; cell?: [number, number] | null; tick: number } | null>(null);
/** 문서 작성 시작 — 양식 고르기 창(FormatPickDialog) */
export const formatPickAtom = atom<boolean>(false);
/** 데이터 설정 창(DataSettingsDialog) */
export const dataSettingsOpenAtom = atom<boolean>(false);
/** 문서가 붙어 있나(양식을 골랐거나 섹션이 있다) — 없으면 가운데 원고 칸을 숨긴다 */
export const hasDocAtom = atom<boolean>(false);
/** 이 작업의 리서치 표·차트와 오른쪽 '결과'에서 보는 것 */
export const tablesAtom = atom<ResearchTable[]>([]);
export const activeTableIdAtom = atom<string | null>(null);

export type RightPanelTab = "result" | "library" | "viewer" | "evidence" | "numbers";
export interface Panels {
  reportOpen: boolean;
  rightOpen: boolean;
  rightTab: RightPanelTab;
  rightWidth: number;
}
export const RIGHT_PANEL_MIN_WIDTH = 300;
export const RIGHT_PANEL_MAX_WIDTH = 640;
/** 리포트·자료 패널은 기본으로 열어 둔다(채팅 | 리포트 | 자료 한 화면) */
export const panelsAtom = atomWithStorage<Panels>(`${STORAGE_PREFIX}.panels`, { reportOpen: true, rightOpen: true, rightTab: "library", rightWidth: 360 });

/** 세션 전환·언마운트 때 전부 초기화(panelsAtom·metaAtom 제외) */
export const resetStudioAtom = atom(null, (_get, set) => {
  set(sessionAtom, null);
  set(reportAtom, null);
  set(readinessAtom, null);
  set(numbersAtom, null);
  set(numberFocusAtom, null);
  set(messagesAtom, []);
  set(suggestionsAtom, []);
  set(documentsAtom, []);
  set(jobsAtom, []);
  set(providerAtom, null);
  set(canChatAtom, false);
  set(reportOwnerAtom, null);
  set(statusStageAtom, null);
  set(streamingAtom, false);
  set(focusStepAtom, null);
  set(composerDraftAtom, { text: "", tick: 0 });
  set(loadingAtom, true);
  set(loadErrorAtom, null);
  set(uploadingAtom, false);
  set(exportingAtom, false);
  set(viewingDocAtom, null);
  set(evidenceFocusAtom, null);
  set(modesAtom, { research: false, writing: false });
  set(hasDocAtom, false);
  set(tablesAtom, []);
  set(activeTableIdAtom, null);
  set(versionsAtom, []);
  set(sourceCheckAtom, null);
  set(formatPickAtom, false);
  set(dataSettingsOpenAtom, false);
});
