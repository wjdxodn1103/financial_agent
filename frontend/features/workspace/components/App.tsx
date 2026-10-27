"use client";

/**
 * 앱의 뿌리 — 계정(데모 로그인) → 워크스페이스 목록 → 워크스페이스(화면 전환)를 정한다.
 * 주소: ?w=<워크스페이스>&v=<화면>&s=<리포트·AI 채팅 대화>&t=<표>&q=<검색어> — 새로고침·뒤로 가기가 같은 화면으로 돌아온다.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSetAtom } from "jotai";

import { Button } from "@/components/ui/button";
import { getMeta } from "../../report/api";
import { metaAtom } from "../../report/atoms";
import { API_BASE } from "../../report/constants";
import type { Meta } from "../../report/types";
import { getUserId, setUserId } from "../auth";
import { WorkspaceProvider, type WorkspaceNav } from "../context";
import type { WorkspaceView } from "../types";
import { Login } from "./Login";
import { WorkspaceHome } from "./WorkspaceHome";
import { WorkspaceShell } from "./WorkspaceShell";

const VIEWS: WorkspaceView[] = ["home", "schedule", "tasks", "search", "channel", "research", "reports", "documents", "company", "assets", "formats", "ledger", "reviews", "requests", "members"];

interface Route {
  w: string | null;
  v: WorkspaceView;
  s: string | null;
  t?: string | null;
  q?: string;
}

function readRoute(): Route {
  const p = new URL(window.location.href).searchParams;
  const v = p.get("v") as WorkspaceView | null;
  return { w: p.get("w"), v: v && VIEWS.includes(v) ? v : "home", s: p.get("s"), t: p.get("t"), q: p.get("q") ?? "" };
}

function writeRoute(r: Route, replace: boolean) {
  const url = new URL(window.location.href);
  url.search = "";
  if (r.w) url.searchParams.set("w", r.w);
  if (r.w && r.v !== "home") url.searchParams.set("v", r.v);
  if (r.w && r.s) url.searchParams.set("s", r.s);
  if (r.w && r.t) url.searchParams.set("t", r.t);
  if (r.w && r.v === "search" && r.q) url.searchParams.set("q", r.q);
  if (replace) window.history.replaceState(null, "", url.toString());
  else window.history.pushState(null, "", url.toString());
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex h-screen flex-col items-center justify-center gap-4 px-6 text-center text-sm text-text-secondary">{children}</div>;
}

export default function App() {
  const setMetaAtom = useSetAtom(metaAtom);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [userId, setUser] = useState<string | null>(null);
  const [route, setRoute] = useState<Route>({ w: null, v: "home", s: null });

  useEffect(() => {
    let cancelled = false;
    setRoute(readRoute());
    setUser(getUserId());
    getMeta()
      .then((m) => {
        if (cancelled) return;
        setMeta(m);
        setMetaAtom(m);
      })
      .catch(() => !cancelled && setError(`백엔드(${API_BASE})에 연결할 수 없습니다. backend 를 실행했는지 확인해 주세요.`));
    const onPop = () => setRoute(readRoute());
    window.addEventListener("popstate", onPop);
    return () => {
      cancelled = true;
      window.removeEventListener("popstate", onPop);
    };
  }, [attempt, setMetaAtom]);

  const go = useCallback((r: Route, replace = false) => {
    writeRoute(r, replace);
    setRoute(r);
  }, []);

  const me = meta?.users.find((u) => u.id === userId) ?? null;

  const logout = useCallback(() => {
    setUserId(null);
    setUser(null);
    go({ w: null, v: "home", s: null }, true);
  }, [go]);

  const nav = useMemo<WorkspaceNav>(
    () => ({
      view: (v) => go({ w: route.w, v, s: null }),
      openReport: (s, t = null, replace = false) => go({ w: route.w, v: "reports", s, t }, replace),
      openResearch: (s, t = null, replace = false) => go({ w: route.w, v: "research", s, t }, replace),
      openAsset: (t) => go({ w: route.w, v: "assets", s: null, t }),
      openFolder: (s) => go({ w: route.w, v: "documents", s }),
      search: (q) => go({ w: route.w, v: "search", s: null, q }),
      leave: () => go({ w: null, v: "home", s: null }),
    }),
    [go, route.w],
  );
  const onMissing = useCallback(() => go({ w: null, v: "home", s: null }, true), [go]);

  if (error) {
    return (
      <Centered>
        <p className="text-red-600">{error}</p>
        <Button
          variant="outline"
          onClick={() => {
            setError(null);
            setAttempt((n) => n + 1);
          }}
        >
          다시 시도
        </Button>
      </Centered>
    );
  }
  if (!meta) {
    return (
      <Centered>
        <span className="dot-bounce inline-flex items-center gap-1" aria-hidden>
          <span />
          <span />
          <span />
        </span>
      </Centered>
    );
  }
  if (!me) {
    return (
      <Login
        users={meta.users}
        onPick={(id) => {
          setUserId(id);
          setUser(id);
        }}
      />
    );
  }
  if (!route.w) {
    return <WorkspaceHome me={me} meta={meta} onOpen={(w) => go({ w, v: "home", s: null })} onLogout={logout} />;
  }
  return (
    <WorkspaceProvider key={`${route.w}:${me.id}`} workspaceId={route.w} me={me} meta={meta} nav={nav} onMissing={onMissing}>
      <WorkspaceShell view={route.v} reportId={route.s} tableId={route.t ?? null} query={route.q ?? ""} onLogout={logout} />
    </WorkspaceProvider>
  );
}
