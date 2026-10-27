"use client";

/**
 * 열린 워크스페이스 — 상세(멤버·내 역할)를 한 번 불러와 아래 화면들이 같이 쓴다.
 * 리포트 스튜디오·자료 보기·근거 탭도 이 컨텍스트에서 workspaceId 를 읽는다(자료가 워크스페이스에 붙어 있다).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { useSetAtom } from "jotai";

import { metaAtom } from "../report/atoms";
import type { Meta, ReportTypeInfo, Role, UserInfo } from "../report/types";
import { listReportTypes } from "../research/api";
import { getWorkspace } from "./api";
import type { WorkspaceDetail, WorkspaceView } from "./types";

/** 작업 목록이 바뀜(턴이 끝남·이름을 저장함) — 사이드바 트리·위쪽 경로가 다시 받는다 */
const TASKS_CHANGED = "dcf:tasks-changed";
export const notifyTasksChanged = () => window.dispatchEvent(new Event(TASKS_CHANGED));
export function useTasksChanged(fn: () => void) {
  useEffect(() => {
    window.addEventListener(TASKS_CHANGED, fn);
    return () => window.removeEventListener(TASKS_CHANGED, fn);
  }, [fn]);
}

const RANK: Record<Role, number> = { viewer: 0, reviewer: 1, editor: 2, owner: 3 };

export interface WorkspaceNav {
  view: (v: WorkspaceView) => void;
  /** AI 작업 — tableId 를 주면 그 표·차트(드라이브 ▸ 에셋)를 작업의 결과에 두고 연다 */
  openReport: (reportId: string | null, tableId?: string | null, replace?: boolean) => void;
  /** AI 채팅 — 대화(null 이면 새 대화 화면), 표(드라이브에서 연 표). replace 면 주소만 바꾼다(첫 메시지로 대화가 생길 때) */
  openResearch: (chatId: string | null, tableId?: string | null, replace?: boolean) => void;
  /** 드라이브 ▸ 에셋에서 그 에셋을 연다 / 드라이브에서 그 폴더를 연다 */
  openAsset: (tableId: string) => void;
  openFolder: (folderId: string) => void;
  /** 위쪽 검색창 → 검색 화면(주소에 q 를 남겨 새로고침·뒤로 가기에도 그대로) */
  search: (q: string) => void;
  leave: () => void;
}

export interface WorkspaceCtx {
  workspaceId: string;
  detail: WorkspaceDetail | null;
  me: UserInfo;
  meta: Meta;
  role: Role;
  can: (min: Role) => boolean;
  nameOf: (userId: string | null | undefined) => string;
  refresh: () => Promise<void>;
  /** 샘플에서 등록한 리포트 양식(rt:)을 다시 받아 meta.reportTypes 에 합친다 */
  refreshTypes: () => Promise<void>;
  setDetail: (d: WorkspaceDetail) => void;
  nav: WorkspaceNav;
}

const Ctx = createContext<WorkspaceCtx | null>(null);

export function WorkspaceProvider({ workspaceId, me, meta: baseMeta, nav, onMissing, children }: { workspaceId: string; me: UserInfo; meta: Meta; nav: WorkspaceNav; onMissing: () => void; children: ReactNode }) {
  const [detail, setDetail] = useState<WorkspaceDetail | null>(null);
  const [registered, setRegistered] = useState<ReportTypeInfo[]>([]);
  const setMetaAtom = useSetAtom(metaAtom);
  // 등록 양식은 워크스페이스·사람마다 달라 meta(전역)에 이 워크스페이스 것만 합친다 — 스튜디오(metaAtom)도 같은 목록을 본다
  const meta = useMemo<Meta>(() => ({ ...baseMeta, reportTypes: [...baseMeta.reportTypes, ...registered] }), [baseMeta, registered]);
  useEffect(() => setMetaAtom(meta), [meta, setMetaAtom]);

  const refreshTypes = useCallback(async () => {
    try {
      setRegistered(await listReportTypes(workspaceId));
    } catch {
      setRegistered([]);
    }
  }, [workspaceId]);

  useEffect(() => {
    void refreshTypes();
  }, [refreshTypes]);

  const refresh = useCallback(async () => {
    try {
      setDetail(await getWorkspace(workspaceId));
    } catch {
      onMissing();
    }
  }, [onMissing, workspaceId]);

  useEffect(() => {
    setDetail(null);
    void refresh();
  }, [refresh]);

  const value = useMemo<WorkspaceCtx>(() => {
    const role: Role = detail?.me.role ?? "viewer";
    const names = new Map((detail?.users ?? meta.users).map((u) => [u.id, `${u.name} ${u.title}`.trim()]));
    return {
      workspaceId,
      detail,
      me,
      meta,
      role,
      can: (min) => RANK[role] >= RANK[min],
      nameOf: (id) => (id ? (names.get(id) ?? id) : "에이전트"),
      refresh,
      refreshTypes,
      setDetail,
      nav,
    };
  }, [detail, me, meta, nav, refresh, refreshTypes, workspaceId]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWorkspace(): WorkspaceCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return v;
}

export function useWorkspaceId(): string {
  return useWorkspace().workspaceId;
}
