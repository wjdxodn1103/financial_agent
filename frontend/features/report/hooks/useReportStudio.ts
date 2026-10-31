"use client";

/**
 * 리포트 스튜디오 상태·동작의 단일 진입점 — OP-FE features/paper/hooks/usePaperStudio.ts 의 이식.
 *
 * <ReportStudioProvider sessionId> 가 세션을 GET 으로 불러와 atoms 에 넣고, 한 턴의 SSE 이벤트를 서버 TranscriptBuilder 와
 * 같은 규칙으로 메시지·리포트에 반영한다. 무거운 잎(리포트 뷰·자료 패널)은 useReportActions() + 필요한 atom 만 구독한다
 * (텍스트 델타마다 다시 그리지 않게). 최신 값 읽기는 jotai store.get(콜백의 stale closure 방지).
 */
import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";
import { useStore } from "jotai";
import { toast } from "sonner";

import { ApiError, cancelTurn, confirmNumber, downloadDocx, getNumbers, getReadiness, getSession, patchSession, removeDocument, removeTemplate, requestReview, uploadDocuments, uploadTemplate } from "../api";
import {
  activeTableIdAtom,
  canChatAtom,
  composerDraftAtom,
  dataScopeAtom,
  documentsAtom,
  evidenceFocusAtom,
  exportingAtom,
  focusStepAtom,
  hasDocAtom,
  jobsAtom,
  loadErrorAtom,
  loadingAtom,
  messagesAtom,
  modesAtom,
  numberFocusAtom,
  numbersAtom,
  panelsAtom,
  providerAtom,
  readinessAtom,
  reportAtom,
  reportOwnerAtom,
  resetStudioAtom,
  RIGHT_PANEL_MAX_WIDTH,
  RIGHT_PANEL_MIN_WIDTH,
  sessionAtom,
  statusStageAtom,
  streamingAtom,
  sourceCheckAtom,
  suggestionsAtom,
  tablesAtom,
  versionsAtom,
  uploadingAtom,
  viewingDocAtom,
  type RightPanelTab,
} from "../atoms";
import { addChart as addChartApi, addNote, importFormat, importItem, insertTable, uploadSample } from "../../research/api";
import type { ResearchTable, TemplateScope, TemplateSpec } from "../../research/types";
import { chooseLedgerValue } from "../../workspace/api";
import { notifyTasksChanged, useWorkspace, useWorkspaceId } from "../../workspace/context";
import { FEATURES } from "../../workspace/features";
import { ERROR_TEXT } from "../constants";
import { streamChat } from "../stream";
import type { Approval, ChatMessage, ChatTurnBody, DataScope, DocumentsPayload, Modes, PublicSession, ReportSection, SessionPayload, StreamError, StreamEvent, ToolRun } from "../types";
import { keepOf, studioDocuments, useDocumentJobs } from "./useDocumentJobs";

const nextId = () => `m${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
const REORDER_DEBOUNCE_MS = 300;
const READINESS_DEBOUNCE_MS = 400;

export interface ApproveBrief {
  label?: string;
  instruction?: string;
  inputs?: Record<string, string>;
}

export interface ReportActions {
  send: (text: string) => Promise<void>;
  stop: () => void;
  approve: (msgId: string, brief?: ApproveBrief) => Promise<void>;
  reject: (msgId: string) => Promise<void>;
  /** 카드의 참고 자료 칩 토글(뺀 자료는 이 섹션 작성에 쓰지 않는다) */
  toggleCardDoc: (msgId: string, docId: string) => void;
  draft: (text: string) => void;
  openSection: (step: string) => void;
  /** cell = 표 칸(행·열) — 양식 표의 칸을 누르면 원본 데이터 칸을 강조 */
  /** quote = 그 문단을 인용한 문장(근거 카드) — 원문 창이 문장 속 금액과 같은 칸을 칠한다 */
  openDocument: (docId: string, chunk?: string, cell?: [number, number] | null, quote?: string | null) => void;
  openCitation: (step: string, sentence: string) => void;
  toggleReport: () => void;
  toggleRightPanel: () => void;
  setRightTab: (tab: RightPanelTab) => void;
  setRightWidth: (px: number) => void;
  // PATCH 계열 — 서버가 받아들였으면 true(실패면 토스트, 화면은 서버 값 그대로)
  patchSection: (step: string, content: string | null) => Promise<boolean>;
  revertSection: (msgId: string, step: string) => Promise<boolean>;
  rename: (step: string, title: string) => Promise<boolean>;
  reorder: (step: string, dir: "up" | "down") => Promise<boolean>;
  remove: (step: string) => Promise<boolean>;
  setReportType: (type: string) => Promise<boolean>;
  setSetup: (setup: Partial<PublicSession["setup"]>) => Promise<boolean>;
  uploadDocuments: (files: File[]) => Promise<void>;
  dismissJob: (jobId: string) => Promise<void>;
  /** 이 작업 채팅에서 AI 가 참고할 데이터 켜고 끄기(작성자) */
  setDataUse: (docId: string, use: boolean) => Promise<boolean>;
  /** 참고 데이터 범위 — 워크스페이스 기본값 / 고른 데이터·폴더(작성자) */
  setDataScope: (scope: DataScope) => Promise<boolean>;
  /** AI 작업 모드(하나씩) */
  setModes: (modes: Modes) => void;
  /** 문서 판 — 지금 상태 남기기 · 그 판으로 되돌리기 */
  saveVersion: (label?: string) => Promise<boolean>;
  restoreVersion: (id: string) => Promise<boolean>;
  /** 오른쪽 '결과'에서 볼 표·차트 */
  setActiveTable: (id: string) => void;
  replaceTable: (t: ResearchTable) => void;
  /** 표·차트를 이 문서의 섹션 뒤에 넣기 */
  insertAsset: (tableId: string, step: string) => Promise<boolean>;
  /** 표 → 막대·꺾은선 차트(결과에 두고 그 차트를 연다) */
  addChart: (tableId: string, type: "bar" | "line") => Promise<void>;
  /** 답 하나를 메모로(에셋, 근거 아님) */
  saveNote: (msgId: string) => Promise<void>;
  /** 밖에서 만든 에셋(문서 보기의 [에셋으로] 등)을 이 작업의 에셋에 두고 연다 */
  attachAsset: (t: ResearchTable) => void;
  /** 양식 샘플(Word·PDF) 올리기 → 카드 턴 */
  importSample: (file: File) => Promise<void>;
  /** 표·차트 카드 등록·건너뛰기(spec 은 고친 양식) */
  importAction: (msgId: string, n: number, body: { action: "register" | "skip"; name?: string; scope?: TemplateScope; spec?: Partial<TemplateSpec> }) => Promise<boolean>;
  /** 리포트 양식 한꺼번에 등록 */
  registerFormat: (msgId: string, body: { name?: string; scope?: TemplateScope }) => Promise<boolean>;
  /** 섹션에 넣은 AI 채팅 표 빼기 */
  removeTable: (step: string, id: string) => Promise<boolean>;
  exportDocx: () => Promise<void>;
  /** DOCX 양식 등록·해제 — 제목 문단이 섹션이 되고 내보내기가 원본 양식에 채운다 */
  setTemplate: (file: File | null) => Promise<void>;
  /** 충돌 카드에서 값 채택(편집자 이상) — 원장 결정 기록이 남고 점검표를 다시 받는다 */
  chooseConflict: (key: string, figureId: string, reason?: string) => Promise<boolean>;
  /** 작성자 → 검토자 작업 항목 + 채널 알림 */
  requestReview: (reviewerId: string, note: string) => Promise<boolean>;
  refreshReadiness: () => Promise<void>;
  /** 본문 숫자 → 숫자 출처 탭에서 그 숫자를 펼친다 */
  openNumber: (key: string) => void;
  /** 사람 확인 표시(취소는 confirmed=false) — 점검표도 다시 받는다 */
  confirmNumber: (key: string, confirmed: boolean, note?: string, raw?: string) => Promise<boolean>;
  reload: () => Promise<void>;
}

const ActionsContext = createContext<{ sessionId: string; actions: ReportActions } | null>(null);

function normalizeMessage(m: ChatMessage): ChatMessage {
  return { ...m, text: m.text ?? "", streaming: false };
}

function isEmptyAssistant(m: ChatMessage | undefined): boolean {
  return Boolean(m) && !m!.text && !m!.approval && !m!.plan && !m!.sectionUpdates?.length;
}

export function errorText(err: StreamError): string {
  return (err.code && ERROR_TEXT[err.code]) || err.message;
}

export function ReportStudioProvider({ sessionId, initialTableId = null, children }: { sessionId: string; initialTableId?: string | null; children: ReactNode }) {
  const store = useStore();
  const ws = useWorkspace();
  /** 드라이브 ▸ 에셋에서 연 표·차트 — 처음 불러올 때 한 번 이 작업의 결과에 둔다 */
  const openTableRef = useRef(initialTableId);
  const workspaceId = useWorkspaceId();
  const abortRef = useRef<AbortController | null>(null);
  /** 되돌리기 — 섹션 단위 이전 본문 스택(이 화면에서 받은 section_update 만) */
  const prevContentRef = useRef<Record<string, (string | undefined)[]>>({});
  const loadSeqRef = useRef(0);
  const reorderTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reorderSnapshotRef = useRef<ReportSection[] | null>(null);
  const reorderWaitersRef = useRef<((ok: boolean) => void)[]>([]);

  useDocumentJobs(workspaceId);

  // ── 세션 로드 ──
  const applyPayload = useCallback(
    (data: SessionPayload, opts?: { keepMessages?: boolean }) => {
      store.set(sessionAtom, data.session);
      store.set(reportAtom, data.report ?? null);
      store.set(suggestionsAtom, data.suggestions ?? []);
      store.set(providerAtom, data.provider ?? null);
      store.set(documentsAtom, data.documents ?? []);
      store.set(dataScopeAtom, data.dataScope ?? null);
      store.set(canChatAtom, Boolean(data.canChat));
      store.set(reportOwnerAtom, data.owner ?? null);
      store.set(modesAtom, data.modes ?? { research: false, writing: true });
      const hadDoc = store.get(hasDocAtom);
      store.set(hasDocAtom, data.hasDoc ?? true);
      store.set(versionsAtom, data.versions ?? []);
      // 문서 열 — 처음 열 때는 문서가 있으면 열고 없으면 닫은 채로(시작 화면이 넓게). 양식을 골라 문서가 생기면 연다
      if (!opts?.keepMessages) store.set(panelsAtom, (p) => ({ ...p, reportOpen: data.hasDoc ?? true }));
      else if (!hadDoc && data.hasDoc) store.set(panelsAtom, (p) => ({ ...p, reportOpen: true }));
      const tables = data.tables ?? [];
      store.set(tablesAtom, tables);
      if (!opts?.keepMessages) store.set(activeTableIdAtom, data.session.currentTableId ?? tables[tables.length - 1]?.id ?? null);
      if (!opts?.keepMessages) store.set(messagesAtom, (data.session.transcript ?? []).map(normalizeMessage));
    },
    [store],
  );

  const applyDocuments = useCallback(
    (d: DocumentsPayload) => {
      const docs = studioDocuments(d.documents ?? [], store.get(sessionAtom)?.dataExcluded, keepOf(store));
      store.set(documentsAtom, docs);
      store.set(jobsAtom, d.jobs ?? []);
      store.set(sessionAtom, (s) => (s ? { ...s, documentIds: docs.filter((x) => !x.off).map((x) => x.id) } : s));
    },
    [store],
  );

  const load = useCallback(
    async (opts?: { keepMessages?: boolean }) => {
      const seq = ++loadSeqRef.current;
      try {
        let data = await getSession(sessionId);
        if (seq !== loadSeqRef.current) return;
        const want = openTableRef.current;
        openTableRef.current = null;
        if (want && !(data.tables ?? []).some((t) => t.id === want) && data.canChat) data = await patchSession(sessionId, { attachTable: want }).catch(() => data);
        if (seq !== loadSeqRef.current) return;
        applyPayload(data, opts);
        if (want && (data.tables ?? []).some((t) => t.id === want)) {
          store.set(activeTableIdAtom, want);
          if (FEATURES.panelTabs) store.set(panelsAtom, (p) => ({ ...p, rightOpen: true, rightTab: "result" }));
        }
        store.set(loadErrorAtom, null);
      } catch (err) {
        if (seq !== loadSeqRef.current) return;
        store.set(loadErrorAtom, err instanceof ApiError && err.status === 404 ? "리포트를 찾을 수 없습니다." : "백엔드에서 리포트를 불러오지 못했습니다.");
      } finally {
        if (seq === loadSeqRef.current) store.set(loadingAtom, false);
      }
    },
    [applyPayload, sessionId, store],
  );

  const dropPendingReorder = useCallback(() => {
    if (reorderTimerRef.current) clearTimeout(reorderTimerRef.current);
    reorderTimerRef.current = null;
    reorderSnapshotRef.current = null;
    const waiters = reorderWaitersRef.current;
    reorderWaitersRef.current = [];
    for (const w of waiters) w(false);
  }, []);

  useEffect(() => {
    abortRef.current?.abort();
    prevContentRef.current = {};
    dropPendingReorder();
    store.set(resetStudioAtom);
    void load();
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
      dropPendingReorder();
      loadSeqRef.current++;
      store.set(resetStudioAtom);
    };
  }, [sessionId, load, store, dropPendingReorder]);

  // 검토 준비 — 리포트 뷰가 바뀔 때마다(불러오기·섹션 작성·편집·되돌리기) 조금 기다렸다 다시 받는다
  const readinessSeqRef = useRef(0);
  const refreshReadiness = useCallback(async () => {
    const seq = ++readinessSeqRef.current;
    try {
      const [r, n] = await Promise.all([getReadiness(sessionId), getNumbers(sessionId)]);
      if (seq === readinessSeqRef.current) {
        store.set(readinessAtom, r);
        store.set(numbersAtom, n);
      }
    } catch {
      /* 점검표·숫자 판정은 보조 정보 — 실패하면 다음 변경 때 다시 */
    }
  }, [sessionId, store]);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsub = store.sub(reportAtom, () => {
      if (timer) clearTimeout(timer);
      if (store.get(reportAtom)) timer = setTimeout(() => void refreshReadiness(), READINESS_DEBOUNCE_MS);
    });
    return () => {
      unsub();
      if (timer) clearTimeout(timer);
    };
  }, [refreshReadiness, store]);

  // 강조는 2.5초 뒤 풀린다
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsub = store.sub(focusStepAtom, () => {
      if (timer) clearTimeout(timer);
      if (store.get(focusStepAtom)) timer = setTimeout(() => store.set(focusStepAtom, null), 2500);
    });
    return () => {
      unsub();
      if (timer) clearTimeout(timer);
    };
  }, [store]);

  // ── 메시지 ──
  const patchMessage = useCallback((id: string, fn: (m: ChatMessage) => ChatMessage) => store.set(messagesAtom, (prev) => prev.map((m) => (m.id === id ? fn(m) : m))), [store]);
  const patchSessionState = useCallback((fn: (s: PublicSession) => PublicSession) => store.set(sessionAtom, (prev) => (prev ? fn(prev) : prev)), [store]);
  const restoreCard = useCallback(
    (cardId: string) => patchMessage(cardId, (m) => ({ ...m, approval: m.approval && { ...m.approval, state: "pending", chosen: undefined } })),
    [patchMessage],
  );

  /** SSE 이벤트 → 메시지·리포트(서버 TranscriptBuilder 와 같은 규칙) */
  const applyEvent = useCallback(
    (msgId: string, e: StreamEvent) => {
      switch (e.type) {
        case "status":
          store.set(statusStageAtom, e.stage);
          break;
        case "text":
          store.set(statusStageAtom, "respond");
          patchMessage(msgId, (m) => ({ ...m, text: m.text + e.delta }));
          break;
        case "text_replace":
          patchMessage(msgId, (m) => ({ ...m, text: e.text }));
          break;
        case "tool_start": {
          const tool: ToolRun = { id: e.id, name: e.name, args: e.args, status: "running" };
          store.set(statusStageAtom, `tool:${e.name}${e.args?.query ? `|“${String(e.args.query).slice(0, 60)}”` : ""}`);
          patchMessage(msgId, (m) => ({ ...m, tools: [...(m.tools ?? []), tool] }));
          break;
        }
        case "tool_end":
          store.set(statusStageAtom, e.summary ? `think|${String(e.summary).slice(0, 80)}` : "think");
          patchMessage(msgId, (m) => ({ ...m, tools: (m.tools ?? []).map((x) => (x.id === e.id ? { ...x, status: e.status, summary: e.summary } : x)) }));
          break;
        case "section_update": {
          const before = store.get(sessionAtom)?.sections.find((s) => s.step === e.step)?.content;
          prevContentRef.current[e.step] = [...(prevContentRef.current[e.step] ?? []), before];
          patchSessionState((s) => ({
            ...s,
            sections: e.sections,
            evidence: { ...(s.evidence ?? {}), [e.step]: { docIds: s.evidence?.[e.step]?.docIds ?? [], checks: e.checks, warnings: e.warnings } },
          }));
          if (e.report) store.set(reportAtom, e.report);
          if (!store.get(hasDocAtom)) store.set(panelsAtom, (p) => ({ ...p, reportOpen: true }));
          store.set(hasDocAtom, true);
          store.set(focusStepAtom, e.step);
          patchMessage(msgId, (m) => ({
            ...m,
            sectionUpdates: [...(m.sectionUpdates ?? []).filter((u) => u.step !== e.step), { step: e.step, title: e.title, chars: e.chars, covers: e.covers, checks: e.checks, warnings: e.warnings, revertable: true }],
          }));
          break;
        }
        case "table_update": {
          const t = e.table;
          store.set(tablesAtom, (prev) => (prev.some((x) => x.id === t.id) ? prev.map((x) => (x.id === t.id ? t : x)) : [...prev, t]));
          store.set(activeTableIdAtom, t.id);
          if (FEATURES.panelTabs) store.set(panelsAtom, (p) => ({ ...p, rightOpen: true, rightTab: "result" }));
          patchMessage(msgId, (m) => ({ ...m, tables: [...(m.tables ?? []).filter((x) => x.id !== t.id), { id: t.id, title: t.title }] }));
          break;
        }
        case "template_saved":
          toast.success(`양식 '${e.template.name}' 을 저장했습니다.`, { position: "top-center" });
          break;
        case "import_item":
          patchMessage(msgId, (m) => ({ ...m, imports: { id: e.importId, items: [...(m.imports?.items ?? []), e.item], format: m.imports?.format ?? null } }));
          break;
        case "import_format":
          patchMessage(msgId, (m) => ({ ...m, imports: { id: e.importId, items: m.imports?.items ?? [], format: e.format } }));
          break;
        case "proposal":
          patchMessage(msgId, (m) => ({ ...m, proposals: [...(m.proposals ?? []), e.proposal] }));
          break;
        case "item_link":
          patchMessage(msgId, (m) => ({ ...m, links: [...(m.links ?? []), e.item] }));
          if (e.item.kind === "file") {
            // 데이터 파일은 바로 문서 보기에
            store.set(viewingDocAtom, (v) => ({ docId: e.item.id, chunk: undefined, cell: null, tick: (v?.tick ?? 0) + 1 }));
            store.set(panelsAtom, (p) => ({ ...p, rightOpen: true, rightTab: "viewer" }));
          }
          break;
        case "outline_update":
          if (e.sections.length && !store.get(hasDocAtom)) {
            store.set(hasDocAtom, true);
            store.set(panelsAtom, (p) => ({ ...p, reportOpen: true })); // 문서가 생기면 문서 열을 연다
          }
          patchSessionState((s) => ({ ...s, sections: e.sections }));
          if (e.report) store.set(reportAtom, e.report);
          break;
        case "setup_update":
          patchSessionState((s) => ({ ...s, setup: e.setup }));
          if (e.report) store.set(reportAtom, e.report);
          break;
        case "approval": {
          const { type: _t, ...rest } = e;
          const approval: Approval = { ...rest, state: "pending" };
          patchMessage(msgId, (m) => ({ ...m, approval }));
          break;
        }
        case "plan_update":
          store.set(messagesAtom, (prev) =>
            prev.map((m) => {
              if (m.id === msgId) return { ...m, plan: { items: e.items, done: e.done, note: e.note, proposed: e.proposed } };
              // 확정 카드가 오면 앞선 제안 카드의 버튼은 접는다
              if (!e.proposed && m.plan?.proposed && !m.plan.resolved) return { ...m, plan: { ...m.plan, resolved: true } };
              return m;
            }),
          );
          break;
        case "suggestions":
          store.set(suggestionsAtom, e.chips ?? []);
          break;
        case "error":
          patchMessage(msgId, (m) => ({ ...m, error: { code: e.code, message: e.message } }));
          break;
        case "done":
          store.set(statusStageAtom, null);
          store.set(streamingAtom, false);
          patchMessage(msgId, (m) => ({ ...m, streaming: false }));
          break;
        default:
          break;
      }
    },
    [patchMessage, patchSessionState, store],
  );

  /** 스트림 시작 전 오류 — 서버에 아무것도 남지 않았다. 카드 답 턴이면 카드를 다시 대기로 */
  const handlePreStreamError = useCallback(
    (asstId: string, err: StreamError, body: ChatTurnBody) => {
      if (err.code === "SESSION_BUSY" || "approval" in body) {
        toast.error(errorText(err), { position: "top-center" });
        store.set(messagesAtom, (prev) => {
          const i = prev.findIndex((m) => m.id === asstId);
          if (i < 0) return prev;
          const dropUser = "text" in body && i > 0 && prev[i - 1].role === "user";
          return prev.filter((_, j) => j !== i && !(dropUser && j === i - 1));
        });
        if ("approval" in body) restoreCard(body.approval.messageId);
        return;
      }
      patchMessage(asstId, (m) => ({ ...m, streaming: false, error: err }));
    },
    [patchMessage, restoreCard, store],
  );

  const handleAbort = useCallback(
    (asstId: string, body: ChatTurnBody) => {
      if ("approval" in body) {
        restoreCard(body.approval.messageId);
        if (isEmptyAssistant(store.get(messagesAtom).find((m) => m.id === asstId))) {
          store.set(messagesAtom, (prev) => prev.filter((m) => m.id !== asstId));
          return;
        }
      }
      patchMessage(asstId, (m) => ({ ...m, streaming: false, aborted: true }));
    },
    [patchMessage, restoreCard, store],
  );

  const runTurn = useCallback(
    async (asstId: string, body: ChatTurnBody) => {
      const ac = new AbortController();
      abortRef.current = ac;
      store.set(streamingAtom, true);
      store.set(statusStageAtom, "route");
      try {
        await streamChat(sessionId, body, { onEvent: (e) => applyEvent(asstId, e), onError: (err) => handlePreStreamError(asstId, err, body), onAbort: () => handleAbort(asstId, body) }, ac.signal);
      } finally {
        if (abortRef.current === ac) abortRef.current = null;
        store.set(streamingAtom, false);
        store.set(statusStageAtom, null);
      }
      // 도구가 문서를 고친 것(표 넣기·양식 붙이기·자리 채우기)까지 화면에 — 턴이 끝나면 한 번 다시 받는다(대화는 그대로)
      void load({ keepMessages: true }).then(notifyTasksChanged);
    },
    [applyEvent, handleAbort, handlePreStreamError, load, sessionId, store],
  );

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || store.get(streamingAtom) || !store.get(sessionAtom)) return;
      const asstId = nextId();
      // 떠 있던 카드는 그대로 둔다 — 나중에 눌러도 서버가 카드에 실린 제목으로 섹션을 찾아 쓴다(loop._write_approved)
      store.set(messagesAtom, (prev) => [...prev, { id: nextId(), role: "user", text: trimmed }, { id: asstId, role: "assistant", text: "", streaming: true }]);
      await runTurn(asstId, { text: trimmed, modes: store.get(modesAtom), tableId: store.get(activeTableIdAtom) });
    },
    [runTurn, store],
  );

  const importSample = useCallback(
    async (file: File) => {
      if (store.get(streamingAtom) || !store.get(sessionAtom)) return;
      let up: { importId: string; name: string };
      try {
        up = await uploadSample(sessionId, file);
      } catch (e) {
        toast.error(e instanceof ApiError && e.status < 500 ? e.message : "올리지 못했습니다.", { position: "top-center" });
        return;
      }
      const asstId = nextId();
      store.set(messagesAtom, (prev) => [...prev, { id: nextId(), role: "user", text: `양식 샘플: ${up.name}`, attachment: up.name }, { id: asstId, role: "assistant", text: "", streaming: true }]);
      await runTurn(asstId, { import: up.importId });
    },
    [runTurn, sessionId, store],
  );

  const importAction = useCallback(
    async (msgId: string, n: number, body: { action: "register" | "skip"; name?: string; scope?: TemplateScope; spec?: Partial<TemplateSpec> }) => {
      const box = store.get(messagesAtom).find((m) => m.id === msgId)?.imports;
      if (!box) return false;
      try {
        const { item } = await importItem(sessionId, box.id, n, body);
        patchMessage(msgId, (m) => ({ ...m, imports: m.imports && { ...m.imports, items: m.imports.items.map((c) => (c.n === n ? item : c)) } }));
        if (body.action === "register") toast.success(`양식 '${item.title}' 을 등록했습니다.`, { position: "top-center" });
        return true;
      } catch (e) {
        toast.error(e instanceof ApiError && e.status < 500 ? e.message : "처리하지 못했습니다.", { position: "top-center" });
        return false;
      }
    },
    [patchMessage, sessionId, store],
  );

  const registerFormat = useCallback(
    async (msgId: string, body: { name?: string; scope?: TemplateScope }) => {
      const box = store.get(messagesAtom).find((m) => m.id === msgId)?.imports;
      if (!box) return false;
      try {
        const r = await importFormat(sessionId, box.id, body);
        patchMessage(msgId, (m) => ({ ...m, imports: m.imports && { ...m.imports, items: r.items, format: r.format } }));
        void ws.refreshTypes();
        toast.success(`리포트 양식 '${r.format.name}' 을 등록했습니다. 새 문서를 만들 때 고를 수 있습니다.`, { position: "top-center" });
        return true;
      } catch (e) {
        toast.error(e instanceof ApiError && e.status < 500 ? e.message : "등록하지 못했습니다.", { position: "top-center" });
        return false;
      }
    },
    [patchMessage, sessionId, store, ws],
  );

  const stop = useCallback(() => {
    // 스트림을 끊고 서버의 턴도 바로 취소한다 — abort 만으로는 서버가 알아채기까지 잠금이 남아 곧바로 다시 보내면 409 가 난다
    abortRef.current?.abort();
    void cancelTurn(sessionId).catch(() => undefined);
  }, [sessionId]);

  const answer = useCallback(
    async (msgId: string, approved: boolean, brief?: ApproveBrief) => {
      const ap = store.get(messagesAtom).find((m) => m.id === msgId)?.approval;
      if (!ap || store.get(streamingAtom) || !store.get(sessionAtom)) return;
      const docs = (ap.documents ?? []).map((d) => d.id).filter((id) => !(ap.excludedDocs ?? []).includes(id));
      patchMessage(msgId, (m) => ({ ...m, approval: m.approval && { ...m.approval, state: approved ? "approved" : "rejected", chosen: brief?.label } }));
      const asstId = nextId();
      store.set(messagesAtom, (prev) => [...prev, { id: asstId, role: "assistant", text: "", streaming: true }]);
      if (approved && brief?.inputs) {
        const filled = Object.fromEntries(Object.entries(brief.inputs).filter(([, v]) => v.trim()));
        patchSessionState((s) => ({ ...s, userInputs: { ...s.userInputs, ...filled } }));
      }
      await runTurn(asstId, {
        approval: {
          approved,
          action: ap.action,
          messageId: msgId,
          steps: ap.steps ?? [],
          covers: ap.covers,
          documents: approved ? docs : undefined,
          instruction: approved ? brief?.instruction : undefined,
          inputs: approved ? brief?.inputs : undefined,
          label: brief?.label,
        },
      });
    },
    [patchMessage, patchSessionState, runTurn, store],
  );

  const toggleCardDoc = useCallback(
    (msgId: string, docId: string) =>
      patchMessage(msgId, (m) => {
        const ap = m.approval;
        if (!ap) return m;
        const ex = ap.excludedDocs ?? [];
        return { ...m, approval: { ...ap, excludedDocs: ex.includes(docId) ? ex.filter((x) => x !== docId) : [...ex, docId] } };
      }),
    [patchMessage],
  );

  // ── 세션 편집(PATCH) — 낙관적 갱신 없이 서버 payload 를 그대로 적용 ──
  const patch = useCallback(
    async (body: Record<string, unknown>): Promise<boolean> => {
      try {
        applyPayload(await patchSession(sessionId, body), { keepMessages: true });
        if (body.setup) notifyTasksChanged();
        return true;
      } catch (e) {
        toast.error(e instanceof ApiError && e.status === 409 ? e.message : "저장하지 못했습니다.", { position: "top-center" });
        return false;
      }
    },
    [applyPayload, sessionId],
  );

  const revertSection = useCallback(
    async (msgId: string, step: string) => {
      const stack = prevContentRef.current[step] ?? [];
      if (!stack.length) {
        toast.error("새로고침 뒤에는 이전 본문을 알 수 없어 되돌릴 수 없습니다.", { position: "top-center" });
        return false;
      }
      const prev = stack.pop();
      const ok = await patch({ step, content: prev ?? null });
      if (!ok) {
        stack.push(prev);
        return false;
      }
      patchMessage(msgId, (m) => ({ ...m, sectionUpdates: (m.sectionUpdates ?? []).map((u) => (u.step === step ? { ...u, undone: true } : u)) }));
      return true;
    },
    [patch, patchMessage],
  );

  const reorder = useCallback(
    (step: string, dir: "up" | "down"): Promise<boolean> => {
      const current = store.get(sessionAtom)?.sections ?? [];
      const ids = current.map((s) => s.step);
      const i = ids.indexOf(step);
      const j = dir === "up" ? i - 1 : i + 1;
      if (i < 0 || j < 0 || j >= ids.length) return Promise.resolve(false);
      // 연타는 화면에 바로, 서버에는 마지막 클릭 뒤 한 번만. 실패하면 연타 전 순서로
      if (!reorderSnapshotRef.current) reorderSnapshotRef.current = current;
      [ids[i], ids[j]] = [ids[j], ids[i]];
      patchSessionState((s) => ({ ...s, sections: ids.map((id) => s.sections.find((x) => x.step === id)!).filter(Boolean) }));
      if (reorderTimerRef.current) clearTimeout(reorderTimerRef.current);
      return new Promise<boolean>((resolve) => {
        reorderWaitersRef.current.push(resolve);
        reorderTimerRef.current = setTimeout(async () => {
          reorderTimerRef.current = null;
          const snapshot = reorderSnapshotRef.current;
          const waiters = reorderWaitersRef.current;
          reorderSnapshotRef.current = null;
          reorderWaitersRef.current = [];
          const ok = await patch({ order: ids });
          if (!ok && snapshot) patchSessionState((s) => ({ ...s, sections: snapshot }));
          for (const w of waiters) w(ok);
        }, REORDER_DEBOUNCE_MS);
      });
    },
    [patch, patchSessionState, store],
  );

  // ── 자료 ──
  const upload = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      store.set(uploadingAtom, true);
      try {
        const d = await uploadDocuments(workspaceId, files);
        applyDocuments(d);
        if (d.errors?.length) toast.error(d.errors.join("\n"), { position: "top-center" });
      } catch {
        toast.error("파일을 올리지 못했습니다.", { position: "top-center" });
      } finally {
        store.set(uploadingAtom, false);
      }
    },
    [applyDocuments, workspaceId, store],
  );

  const docCall = useCallback(
    async (call: () => Promise<DocumentsPayload>, fail: string) => {
      try {
        applyDocuments(await call());
      } catch (e) {
        toast.error(e instanceof ApiError && e.status === 409 ? e.message : fail, { position: "top-center" });
      }
    },
    [applyDocuments],
  );

  const exportDocx = useCallback(async () => {
    if (store.get(exportingAtom)) return;
    store.set(exportingAtom, true);
    try {
      await downloadDocx(sessionId);
    } catch {
      toast.error("내보내지 못했습니다.", { position: "top-center" });
    } finally {
      store.set(exportingAtom, false);
    }
  }, [sessionId, store]);

  const actions = useMemo<ReportActions>(
    () => ({
      send,
      importSample,
      importAction,
      registerFormat,
      stop,
      approve: (msgId, brief) => answer(msgId, true, brief),
      reject: (msgId) => answer(msgId, false),
      toggleCardDoc,
      draft: (text) => store.set(composerDraftAtom, (d) => ({ text, tick: d.tick + 1 })),
      openSection: (step) => {
        store.set(panelsAtom, (p) => ({ ...p, reportOpen: true }));
        store.set(focusStepAtom, step);
      },
      openDocument: (docId, chunk, cell, quote) => {
        // 위치가 있는 것(표 칸·인용·답 속 출처) = 원문 확인 창(원본 파일 그대로), 자료 자체 = 문서 보기 탭(탭을 끈 동안은 이것도 원문 확인 창)
        if (chunk || !FEATURES.panelTabs) {
          store.set(sourceCheckAtom, { docId, chunk, cell: cell ?? null, quote: quote ?? null, tick: Date.now() });
          return;
        }
        store.set(viewingDocAtom, (v) => ({ docId, chunk, cell: cell ?? null, tick: (v?.tick ?? 0) + 1 }));
        store.set(panelsAtom, (p) => ({ ...p, rightOpen: true, rightTab: "viewer" }));
      },
      openCitation: (step, sentence) => {
        store.set(evidenceFocusAtom, (v) => ({ step, sentence, tick: (v?.tick ?? 0) + 1 }));
        // 탭을 끈 동안은 '데이터' 패널 위에 그 문장의 출처
        store.set(panelsAtom, (p) => ({ ...p, rightOpen: true, ...(FEATURES.panelTabs ? { rightTab: "evidence" as const } : {}) }));
      },
      toggleReport: () => store.set(panelsAtom, (p) => ({ ...p, reportOpen: !p.reportOpen })),
      toggleRightPanel: () => store.set(panelsAtom, (p) => ({ ...p, rightOpen: !p.rightOpen })),
      setRightTab: (tab) => store.set(panelsAtom, (p) => ({ ...p, rightTab: tab, rightOpen: true })),
      setRightWidth: (px) => store.set(panelsAtom, (p) => ({ ...p, rightWidth: Math.round(Math.min(RIGHT_PANEL_MAX_WIDTH, Math.max(RIGHT_PANEL_MIN_WIDTH, px))) })),
      patchSection: (step, content) => patch({ step, content }),
      revertSection,
      rename: (step, title) => (title.trim() ? patch({ step, title: title.trim() }) : Promise.resolve(false)),
      reorder,
      remove: (step) => patch({ remove: step }),
      setReportType: (type) => patch({ reportType: type }),
      setSetup: (setup) => patch({ setup }),
      uploadDocuments: upload,
      dismissJob: (jobId) => docCall(() => removeDocument(workspaceId, { job: jobId }), "목록에서 지우지 못했습니다."),
      setDataUse: (docId, use) => patch({ data: { docId, use } }),
      setDataScope: (scope) => patch({ dataScope: scope }),
      setModes: (modes) => {
        store.set(modesAtom, modes);
        // 다음에 열어도 같은 모드(턴마다 보내기도 한다). 문서 작성에서 나가면 서버가 문서를 판으로 남긴다 — 판 목록을 받아 둔다
        void patchSession(sessionId, { modes })
          .then((p) => applyPayload(p, { keepMessages: true }))
          .catch(() => undefined);
      },
      saveVersion: (label) => patch({ saveVersion: label ?? "" }),
      restoreVersion: (id) => patch({ restoreVersion: id }),
      setActiveTable: (id) => {
        store.set(activeTableIdAtom, id);
        if (FEATURES.panelTabs) store.set(panelsAtom, (p) => ({ ...p, rightOpen: true, rightTab: "result" }));
      },
      replaceTable: (t) => store.set(tablesAtom, (prev) => prev.map((x) => (x.id === t.id ? t : x))),
      insertAsset: async (tableId, step) => {
        try {
          applyPayload(await insertTable(sessionId, tableId, step), { keepMessages: true });
          toast.success("문서에 넣었습니다.", { position: "top-center" });
          return true;
        } catch (e) {
          toast.error(e instanceof ApiError && e.status < 500 ? e.message : "넣지 못했습니다.", { position: "top-center" });
          return false;
        }
      },
      saveNote: async (msgId) => {
        try {
          const p = await addNote(sessionId, msgId);
          applyPayload(p, { keepMessages: true });
          if (p.session.currentTableId) {
            store.set(activeTableIdAtom, p.session.currentTableId);
            if (FEATURES.panelTabs) store.set(panelsAtom, (x) => ({ ...x, rightOpen: true, rightTab: "result" }));
          }
          toast.success("메모로 남겼습니다.", { position: "top-center" });
        } catch (e) {
          toast.error(e instanceof ApiError && e.status < 500 ? e.message : "메모로 남기지 못했습니다.", { position: "top-center" });
        }
      },
      attachAsset: (t) => {
        store.set(tablesAtom, (prev) => (prev.some((x) => x.id === t.id) ? prev : [...prev, t]));
        store.set(activeTableIdAtom, t.id);
        if (FEATURES.panelTabs) store.set(panelsAtom, (x) => ({ ...x, rightOpen: true, rightTab: "result" }));
        void patchSession(sessionId, { attachTable: t.id }).catch(() => undefined);
      },
      addChart: async (tableId, type) => {
        const p = await addChartApi(sessionId, tableId, type);
        applyPayload(p, { keepMessages: true });
        if (p.session.currentTableId) {
          store.set(activeTableIdAtom, p.session.currentTableId);
          if (FEATURES.panelTabs) store.set(panelsAtom, (x) => ({ ...x, rightOpen: true, rightTab: "result" }));
        }
      },
      removeTable: (step, id) => patch({ removeTable: { step, id } }),
      exportDocx,
      setTemplate: async (file) => {
        try {
          applyPayload(file ? await uploadTemplate(sessionId, file) : await removeTemplate(sessionId), { keepMessages: true });
          toast.success(file ? "양식을 등록했습니다. 양식의 제목이 섹션이 됐습니다." : "양식을 해제했습니다.", { position: "top-center" });
        } catch (e) {
          toast.error(e instanceof ApiError && e.status < 500 ? e.message : "양식을 처리하지 못했습니다.", { position: "top-center" });
        }
      },
      reload: async () => {
        store.set(loadingAtom, true);
        await load();
      },
      chooseConflict: async (key, figureId, reason = "") => {
        try {
          await chooseLedgerValue(workspaceId, key, figureId, reason);
          await refreshReadiness();
          return true;
        } catch (e) {
          toast.error(e instanceof ApiError && e.status < 500 ? e.message : "채택하지 못했습니다.", { position: "top-center" });
          return false;
        }
      },
      requestReview: async (reviewerId, note) => {
        try {
          store.set(readinessAtom, await requestReview(sessionId, reviewerId, note));
          return true;
        } catch (e) {
          toast.error(e instanceof ApiError && e.status < 500 ? e.message : "검토를 요청하지 못했습니다.", { position: "top-center" });
          return false;
        }
      },
      refreshReadiness,
      openNumber: (key) => {
        store.set(numberFocusAtom, (v) => ({ key, tick: (v?.tick ?? 0) + 1 }));
        store.set(panelsAtom, (p) => ({ ...p, rightOpen: true, rightTab: "numbers" }));
      },
      confirmNumber: async (key, confirmed, note = "", raw = "") => {
        try {
          store.set(numbersAtom, await confirmNumber(sessionId, key, confirmed, note, raw));
          void getReadiness(sessionId)
            .then((r) => store.set(readinessAtom, r))
            .catch(() => undefined);
          return true;
        } catch (e) {
          toast.error(e instanceof ApiError && e.status < 500 ? e.message : "확인 표시를 남기지 못했습니다.", { position: "top-center" });
          return false;
        }
      },
    }),
    [answer, applyPayload, docCall, exportDocx, importAction, importSample, load, patch, refreshReadiness, registerFormat, reorder, revertSection, send, sessionId, stop, store, toggleCardDoc, upload, workspaceId],
  );

  const value = useMemo(() => ({ sessionId, actions }), [sessionId, actions]);
  return createElement(ActionsContext.Provider, { value }, children);
}

/** 작성 화면 밖(AI 채팅 결과 패널)에서도 쓰는 블록용 — 없으면 null */
export function useMaybeReportActions(): ReportActions | null {
  return useContext(ActionsContext)?.actions ?? null;
}

/** actions 만 — 텍스트 델타로 바뀌지 않는다. 상태는 각 컴포넌트가 필요한 atom 을 직접 구독한다 */
export function useReportActions(): ReportActions {
  const ctx = useContext(ActionsContext);
  if (!ctx) throw new Error("useReportActions must be used inside <ReportStudioProvider>");
  return ctx.actions;
}
