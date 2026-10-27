"use client";

/**
 * 워크스페이스 화면 — 문서형 업무 툴의 뼈대: 왼쪽 공간 사이드바(페이지 트리) + 위쪽 경로·검색 + 본문.
 * 메뉴 = 홈 · 드라이브 · AI 작업 · 문서 양식 · 문서 검수. AI 작업(대화 + 리서치·문서 작성 모드)을 누르면 빈 작업이 열리고, 내 작업 목록이 트리로 펼쳐진다
 * (아무것도 안 한 빈 작업은 목록에서 뺀다 — 새 작업 버튼 없이 'AI 작업'이 곧 새 작업).
 * 팀원끼리 쓰는 채널(FEATURES.teamChannel)·따로 떨어진 AI 채팅(FEATURES.researchChat)은 꺼 두었다 — 대화는 내 것만.
 * 숨긴 화면(근거 원장·할 일 — FEATURES)은 메뉴에서 빠지지만 화면 주소(?v=)는 그대로라 예전 링크도 열린다.
 * 리포트·대화를 열면 사이드바는 아이콘 줄로 접힌다 — 펼치기 버튼으로 다시 연다.
 */
import { useCallback, useEffect, useState, type ComponentType, type FormEvent } from "react";
import { ChevronLeft, ClipboardCheck, FileText, HardDrive, Home, LayoutTemplate, LogOut, MessageSquare, MessagesSquare, PanelLeftClose, PanelLeftOpen, Plus, Search, Settings, Sparkles, Users } from "lucide-react";

import { cn } from "@/lib/utils";
import { FormatsView } from "../../formats/FormatsView";
import type { SessionListItem } from "../../report/types";
import { listChats } from "../../research/api";
import { ResearchView } from "../../research/ResearchView";
import type { ChatSummary } from "../../research/types";
import { listReports } from "../api";
import { useTasksChanged, useWorkspace } from "../context";
import { FEATURES } from "../features";
import type { WorkspaceView } from "../types";
import { Brand } from "./Brand";
import { RoleBadge } from "./RoleBadge";
import { ChannelView } from "./views/ChannelView";
import { CompanyDriveView } from "./views/CompanyDriveView";
import { AssetsView } from "./views/AssetsView";
import { DriveView } from "./views/DriveView";
import { HomeView } from "./views/HomeView";
import { LedgerView } from "./views/LedgerView";
import { MembersView } from "./views/MembersView";
import { ReportsView } from "./views/ReportsView";
import { ReviewsView } from "./views/ReviewsView";
import { SearchView } from "./views/SearchView";
import { RequestsView } from "./views/RequestsView";
import { ScheduleView } from "./views/ScheduleView";
import { TasksView } from "./views/TasksView";

type Icon = ComponentType<{ className?: string }>;
interface Group {
  id: string;
  label: string;
  icon: Icon;
  views: WorkspaceView[];
  children?: { view: WorkspaceView; label: string }[];
}

// 묶음을 누르면 첫 화면으로 가고, 하위 화면은 트리로 펼쳐진다. 첫 화면이 하위 목록에 없으면(홈) 묶음 줄이 그 화면이다.
// 숨긴 화면(근거 원장 — FEATURES.ledgerView)은 묶음에서 빠진다.
const GROUPS: Group[] = [
  {
    id: "home",
    label: "홈",
    icon: Home,
    views: ["home", "schedule", "tasks"],
    children: [
      { view: "schedule", label: "일정" },
      { view: "tasks", label: "할 일" },
    ],
  },
  {
    id: "drive",
    label: "드라이브",
    icon: HardDrive,
    views: ["documents", "company", ...(FEATURES.assets ? (["assets"] as const) : []), ...(FEATURES.ledgerView ? (["ledger"] as const) : [])],
    children: [
      { view: "documents", label: "워크스페이스" },
      { view: "company", label: "사내 공용" },
      ...(FEATURES.assets ? [{ view: "assets" as const, label: "에셋" }] : []),
      ...(FEATURES.ledgerView ? [{ view: "ledger" as const, label: "근거 원장" }] : []),
    ],
  },
  { id: "write", label: "AI 작업", icon: Sparkles, views: ["reports"] },
  { id: "formats", label: "문서 양식", icon: LayoutTemplate, views: ["formats"] },
  {
    id: "review",
    label: "문서 검수",
    icon: ClipboardCheck,
    views: ["reviews", "requests"],
    children: [
      { view: "reviews", label: "검수" },
      { view: "requests", label: "검토 요청" },
    ],
  },
  ...(FEATURES.researchChat ? [{ id: "chat", label: "AI 채팅", icon: MessageSquare, views: ["research" as const] }] : []),
  ...(FEATURES.teamChannel ? [{ id: "team", label: "팀 채팅", icon: MessagesSquare, views: ["channel" as const] }] : []),
];

const VIEW_LABEL: Record<WorkspaceView, string> = {
  home: "홈",
  schedule: "일정",
  tasks: "할 일",
  search: "검색",
  channel: "팀 채팅",
  research: "AI 채팅",
  reports: "AI 작업",
  documents: "워크스페이스",
  company: "사내 공용",
  assets: "에셋",
  formats: "문서 양식",
  ledger: "근거 원장",
  reviews: "검수",
  requests: "검토 요청",
  members: "멤버·설정",
};

function groupOf(view: WorkspaceView): Group | undefined {
  return GROUPS.find((g) => g.views.includes(view));
}

function TreeItem({ on, onClick, children, depth = 0 }: { on: boolean; onClick: () => void; children: React.ReactNode; depth?: 0 | 1 }) {
  return (
    <button
      type="button"
      aria-current={on ? "page" : undefined}
      onClick={onClick}
      className={cn(
        "flex w-full cursor-pointer items-center gap-2 rounded-lg text-left transition-colors",
        depth ? "py-1.5 pr-2 pl-9 text-[13px]" : "px-2.5 py-2 text-[14px]",
        on ? "bg-primary-soft font-semibold text-primary" : depth ? "text-text-secondary hover:bg-neutral-100 hover:text-text-primary" : "font-medium text-neutral-700 hover:bg-neutral-100",
      )}
    >
      {children}
    </button>
  );
}

export function WorkspaceShell({ view, reportId, tableId, query, onLogout }: { view: WorkspaceView; reportId: string | null; tableId: string | null; query: string; onLogout: () => void }) {
  const ws = useWorkspace();
  const info = ws.detail?.workspace;
  const kind = ws.meta.workspaceKinds.find((k) => k.id === info?.kind)?.title;
  const active = groupOf(view);
  const [reports, setReports] = useState<SessionListItem[]>([]);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [q, setQ] = useState(query);
  const [pinned, setPinned] = useState(false);
  const opened = (view === "reports" || view === "research") && !!reportId;
  const rail = opened && !pinned;

  useEffect(() => setQ(query), [query]);

  // AI 작업 묶음의 페이지 트리 — 내 작업 목록(열 때·작업을 바꿀 때·턴이 끝나거나 이름을 저장할 때 다시). 대화는 개인이라 남의 작업은 없다(남의 문서는 드라이브에서)
  const [tasksTick, setTasksTick] = useState(0);
  useTasksChanged(useCallback(() => setTasksTick((n) => n + 1), []));
  useEffect(() => {
    if (active?.id !== "write") return;
    let cancelled = false;
    void listReports(ws.workspaceId)
      .then((xs) => !cancelled && setReports(xs.filter((x) => x.createdBy === ws.me.id && !x.empty)))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [active?.id, reportId, tasksTick, ws.workspaceId, ws.me.id]);

  // AI 채팅 묶음의 대화 목록(내 것만)
  useEffect(() => {
    if (active?.id !== "chat") return;
    let cancelled = false;
    void listChats(ws.workspaceId)
      .then((xs) => !cancelled && setChats(xs))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [active?.id, reportId, ws.workspaceId]);

  const openGroup = (g: Group) => (g.id === "write" ? ws.nav.openReport(null) : g.id === "chat" ? ws.nav.openResearch(null) : ws.nav.view(g.views[0]));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (q.trim()) ws.nav.search(q.trim());
  };

  const crumbs = [info?.name ?? "…", ...(active && active.id !== "home" ? [active.label] : []), ...(view !== "home" && (active?.children || !active) ? [VIEW_LABEL[view]] : [])];
  const reportTitle = reportId ? (view === "research" ? chats.find((c) => c.id === reportId)?.title : reports.find((r) => r.id === reportId)?.title) : null;

  return (
    <div className="flex h-screen min-h-0 w-full bg-white">
      {rail ? (
        <aside className="flex w-[60px] shrink-0 flex-col items-center gap-1 border-r border-neutral-200 bg-[#fbfcfd] py-3">
          <Brand compact />
          <button
            type="button"
            title="사이드바 펼치기"
            aria-label="사이드바 펼치기"
            onClick={() => setPinned(true)}
            className="mt-3 cursor-pointer rounded-lg p-2 text-neutral-500 hover:bg-neutral-100"
          >
            <PanelLeftOpen className="size-[18px]" aria-hidden />
          </button>
          <span className="my-2 h-px w-8 bg-neutral-200" />
          {GROUPS.map((g) => {
            const Icon = g.icon;
            const on = active?.id === g.id;
            return (
              <button
                key={g.id}
                type="button"
                title={g.label}
                aria-label={g.label}
                onClick={() => openGroup(g)}
                className={cn("cursor-pointer rounded-lg p-2.5 transition-colors", on ? "bg-primary-soft text-primary" : "text-neutral-500 hover:bg-neutral-100")}
              >
                <Icon className="size-[18px]" />
              </button>
            );
          })}
          <span className="mt-auto flex size-8 items-center justify-center rounded-full bg-neutral-200 text-[13px] font-bold text-neutral-700" title={`${ws.me.name} ${ws.me.title}`}>
            {ws.me.name.slice(0, 1)}
          </span>
        </aside>
      ) : (
        <aside className="flex w-[248px] shrink-0 flex-col border-r border-neutral-200 bg-[#fbfcfd]">
          <div className="flex items-center justify-between px-4 pt-4">
            <Brand />
            {opened && (
              <button type="button" title="사이드바 접기" aria-label="사이드바 접기" onClick={() => setPinned(false)} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
                <PanelLeftClose className="size-4" aria-hidden />
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={ws.nav.leave}
            className="mx-3 mt-4 flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-1 text-[12px] text-text-secondary hover:bg-neutral-100 hover:text-text-primary"
          >
            <ChevronLeft className="size-3.5" aria-hidden />
            모든 워크스페이스
          </button>
          <div className="mx-3 mt-1 flex items-center gap-2.5 rounded-xl bg-white px-2.5 py-2.5 ring-1 ring-neutral-200">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-primary-soft text-[15px] font-bold text-primary">{(info?.name ?? "?").slice(0, 1)}</span>
            <span className="min-w-0">
              <span className="block truncate text-[14px] font-bold text-text-primary" title={info?.name}>
                {info?.name ?? "…"}
              </span>
              <span className="block truncate text-[12px] text-text-secondary">{kind ?? ""}</span>
            </span>
          </div>

          <nav className="thin-scrollbar mt-4 flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-3 pb-3">
            {GROUPS.map((g) => {
              const Icon = g.icon;
              const isActive = active?.id === g.id;
              return (
                <div key={g.id}>
                  <TreeItem on={isActive && !g.children?.some((c) => c.view === view) && !((g.id === "write" || g.id === "chat") && reportId)} onClick={() => openGroup(g)}>
                    <Icon className={cn("size-[18px]", isActive ? "text-primary" : "text-neutral-500")} />
                    {g.label}
                  </TreeItem>
                  {isActive &&
                    g.children?.map((c) => (
                      <TreeItem key={c.view} depth={1} on={view === c.view} onClick={() => ws.nav.view(c.view)}>
                        {c.label}
                      </TreeItem>
                    ))}
                  {isActive && g.id === "write" && (
                    <>
                      {reports.map((r) => (
                        <TreeItem key={r.id} depth={1} on={reportId === r.id} onClick={() => ws.nav.openReport(r.id)}>
                          {r.hasDoc === false ? <MessageSquare className="size-3.5 shrink-0" aria-hidden /> : <FileText className="size-3.5 shrink-0" aria-hidden />}
                          <span className="truncate">{r.title || "새 작업"}</span>
                        </TreeItem>
                      ))}
                    </>
                  )}
                  {isActive && g.id === "chat" && (
                    <>
                      <TreeItem depth={1} on={false} onClick={() => ws.nav.openResearch(null)}>
                        <Plus className="size-3.5 shrink-0" aria-hidden />새 대화
                      </TreeItem>
                      {chats.map((c) => (
                        <TreeItem key={c.id} depth={1} on={reportId === c.id} onClick={() => ws.nav.openResearch(c.id)}>
                          <MessageSquare className="size-3.5 shrink-0" aria-hidden />
                          <span className="truncate">{c.title || "새 대화"}</span>
                        </TreeItem>
                      ))}
                    </>
                  )}
                </div>
              );
            })}
          </nav>

          <div className="border-t border-neutral-200 px-3 py-3">
            <TreeItem on={view === "members"} onClick={() => ws.nav.view("members")}>
              <Settings className={cn("size-[18px]", view === "members" ? "text-primary" : "text-neutral-500")} />
              멤버·설정
              <span className="ml-auto flex items-center gap-0.5 text-[12px] font-normal text-text-secondary">
                <Users className="size-3" aria-hidden />
                {ws.detail?.members.length ?? 0}
              </span>
            </TreeItem>
            <div className="mt-2 flex items-center gap-2.5 px-2">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-neutral-200 text-[13px] font-bold text-neutral-700">{ws.me.name.slice(0, 1)}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-semibold text-text-primary">
                  {ws.me.name} {ws.me.title}
                </span>
                <RoleBadge role={ws.role} className="mt-0.5 inline-block" />
              </span>
              <button
                type="button"
                title="계정 바꾸기"
                aria-label="계정 바꾸기"
                onClick={onLogout}
                className="cursor-pointer rounded-md p-1.5 text-text-secondary hover:bg-neutral-100 hover:text-text-primary"
              >
                <LogOut className="size-4" aria-hidden />
              </button>
            </div>
          </div>
        </aside>
      )}

      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-neutral-200 px-5">
          <nav aria-label="경로" className="flex min-w-0 items-center gap-1.5 text-[13px] text-text-secondary">
            {crumbs.map((c, i) => (
              <span key={i} className="flex min-w-0 items-center gap-1.5">
                {i > 0 && <span className="text-neutral-300">/</span>}
                {i === 0 && view !== "home" ? (
                  <button type="button" onClick={() => ws.nav.view("home")} className="cursor-pointer truncate hover:text-text-primary hover:underline">
                    {c}
                  </button>
                ) : (
                  <span className={cn("truncate", i === crumbs.length - 1 && !reportTitle && "font-semibold text-text-primary")}>{c}</span>
                )}
              </span>
            ))}
            {reportTitle && (
              <>
                <span className="text-neutral-300">/</span>
                <span className="truncate font-semibold text-text-primary">{reportTitle}</span>
              </>
            )}
          </nav>
          <form
            onSubmit={submit}
            className="flex w-[300px] shrink-0 items-center gap-2 rounded-full bg-neutral-100 px-3.5 py-1.5 focus-within:bg-white focus-within:ring-2 focus-within:ring-primary/30"
          >
            <Search className="size-4 text-neutral-500" aria-hidden />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="이 워크스페이스에서 찾기"
              aria-label="워크스페이스 검색"
              className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-neutral-500"
            />
          </form>
        </header>

        <div className="flex min-h-0 flex-1 flex-col">
          {!ws.detail ? (
            <div className="flex flex-1 items-center justify-center text-sm text-text-secondary">불러오는 중…</div>
          ) : view === "reports" ? (
            <ReportsView reportId={reportId} tableId={tableId} />
          ) : view === "documents" ? (
            <DriveView key={reportId ?? ""} initialFolder={reportId} />
          ) : view === "company" ? (
            <CompanyDriveView />
          ) : view === "assets" ? (
            <AssetsView key={tableId ?? ""} initialOpen={tableId} />
          ) : view === "formats" ? (
            <FormatsView />
          ) : view === "ledger" ? (
            <LedgerView />
          ) : view === "research" ? (
            <ResearchView chatId={reportId} tableId={tableId} />
          ) : view === "channel" ? (
            <ChannelView />
          ) : view === "tasks" ? (
            <TasksView />
          ) : view === "schedule" ? (
            <ScheduleView />
          ) : view === "reviews" ? (
            <ReviewsView />
          ) : view === "requests" ? (
            <RequestsView />
          ) : view === "members" ? (
            <MembersView />
          ) : view === "search" ? (
            <SearchView query={query} />
          ) : (
            <HomeView />
          )}
        </div>
      </main>
    </div>
  );
}
