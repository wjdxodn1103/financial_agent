"use client";

import { createContext, useContext } from "react";

import type { ReportTypeId } from "./types";

/** 리포트 바꾸기·새로 만들기·목록으로 — 워크스페이스의 리포트 화면이 주고 상단 바 메뉴가 쓴다 */
export interface AppNav {
  open: (id: string) => void;
  create: (reportType?: ReportTypeId) => Promise<void>;
  back: () => void;
}

export const NavContext = createContext<AppNav | null>(null);

export function useAppNav(): AppNav {
  const v = useContext(NavContext);
  if (!v) throw new Error("useAppNav must be used inside <NavContext.Provider>");
  return v;
}
