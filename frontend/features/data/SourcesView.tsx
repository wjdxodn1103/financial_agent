"use client";

/**
 * 드라이브 ▸ 수집 소스 — 사내 DB 에 AI 가 쓰기 좋게 계속 적재하는 소스(공시·시장 시계열·공식 보도자료·수집 폴더).
 * 사내 공용은 관리자가, 워크스페이스 소스는 편집자 이상이 등록한다. 모은 것은 보통 문서가 되어 AI 검색·작성·원문 창에 그대로 쓰인다.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Building2, CalendarClock, FileSpreadsheet, FolderInput, Loader2, Newspaper, Play, Plus, RotateCcw, TrendingUp, X } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ApiError } from "../report/api";
import { useWorkspace } from "../workspace/context";
import { PageHeader } from "../workspace/components/views/PageHeader";
import { useOpenSource } from "../workspace/sourceHost";
import { deleteSource, listSourceItems, listSourceRuns, listSources, retrySourceItem, runSource, updateSource } from "./api";
import { AddSourceDialog } from "./AddSourceDialog";
import type { SourceInfo, SourceItemView, SourceKind, SourceRunView } from "./types";

export const KIND_ICON: Record<SourceKind, typeof TrendingUp> = { series: TrendingUp, rss: Newspaper, edgar: FileSpreadsheet, folder: FolderInput };
const STATUS_KO: Record<string, string> = { ok: "정상", partial: "일부 실패", error: "실패", running: "수집 중", skipped: "건너뜀" };
const WEEK = ["월", "화", "수", "목", "금", "토", "일"];

export function scheduleText(s: SourceInfo["schedule"]): string {
  const t = (s.times || []).join(" · ");
  switch (s.every) {
    case "manual":
      return "손으로만";
    case "hourly":
      return "매시간";
    case "weekdays":
      return `평일 ${t}`;
    case "weekly":
      return `매주 ${WEEK[s.weekday ?? 0]} ${t}`;
    default:
      return `매일 ${t}`;
  }
}

export function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const host = (u: string) => {
  try {
    return u ? new URL(u).hostname : null;
  } catch {
    return null;
  }
};

const errText = (e: unknown, fallback: string) => (e instanceof ApiError && e.status < 500 ? e.message : fallback);

export function SourcesView({ initialSource }: { initialSource: string | null }) {
  const ws = useWorkspace();
  const [rows, setRows] = useState<SourceInfo[] | null>(null);
  const [admin, setAdmin] = useState(false);
  const [open, setOpen] = useState<string | null>(initialSource);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await listSources(ws.workspaceId);
      setRows(r.sources);
      setAdmin(r.isAdmin);
    } catch {
      setRows([]);
    }
  }, [ws.workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);
  // 수집 중이면 3초마다 다시
  const running = rows?.some((r) => r.lastRun?.status === "running");
  useEffect(() => {
    if (!running) return;
    const t = window.setTimeout(() => void load(), 3000);
    return () => window.clearTimeout(t);
  }, [running, rows, load]);

  const groups = useMemo(() => {
    const all = rows ?? [];
    return [
      { id: "company", label: "사내 공용", items: all.filter((r) => r.scope === "company") },
      { id: "workspace", label: ws.detail?.workspace.name ?? "이 워크스페이스", items: all.filter((r) => r.scope === "workspace") },
    ];
  }, [rows, ws.detail?.workspace.name]);

  const run = async (s: SourceInfo, asOf?: string) => {
    try {
      await runSource(s.id, asOf);
      toast.success(asOf ? `${asOf} 기준으로 수집을 시작했습니다.` : "수집을 시작했습니다.", { position: "top-center" });
      window.setTimeout(() => void load(), 800);
    } catch (e) {
      toast.error(errText(e, "수집을 시작하지 못했습니다."), { position: "top-center" });
    }
  };

  const current = rows?.find((r) => r.id === open) ?? null;
  const canAdd = admin || ws.can("editor");

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
      <PageHeader
        title="수집 소스"
        wide
        actions={
          canAdd && (
            <button type="button" onClick={() => setAdding(true)} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover">
              <Plus className="size-4" aria-hidden />
              소스 추가
            </button>
          )
        }
      />
      <div className="mx-auto flex max-w-[1180px] flex-col gap-6 px-8 pb-12">
        {rows === null && <p className="py-10 text-center text-[14px] text-text-secondary">불러오는 중…</p>}
        {groups.map((g) =>
          g.items.length === 0 && g.id === "company" ? null : (
            <section key={g.id}>
              <h2 className="mb-2 flex items-center gap-1.5 px-1 text-[13px] font-semibold text-text-secondary">
                {g.id === "company" && <Building2 className="size-3.5" aria-hidden />}
                {g.label}
              </h2>
              {g.items.length === 0 ? (
                <p className="rounded-[20px] bg-white px-6 py-8 text-center text-[13px] text-text-secondary">등록한 소스가 없습니다.</p>
              ) : (
                <div className="overflow-hidden rounded-[20px] bg-white">
                  {g.items.map((s) => {
                    const Icon = KIND_ICON[s.kind];
                    const st = s.lastRun?.status ?? "";
                    return (
                      <div key={s.id} className={cn("flex items-center gap-4 border-b border-neutral-100 px-5 py-3.5 last:border-0", open === s.id && "bg-primary-soft/40")}>
                        <button type="button" onClick={() => setOpen(s.id)} className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 text-left">
                          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-neutral-100 text-primary">
                            <Icon className="size-[18px]" aria-hidden />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2">
                              <span className="truncate text-[14px] font-semibold text-text-primary">{s.name}</span>
                              {!s.enabled && <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-text-secondary">꺼 둠</span>}
                              {s.mode === "fixture" && <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700">가상</span>}
                            </span>
                            <span className="mt-0.5 block truncate text-[12px] text-text-secondary">
                              {s.kindKo} · {scheduleText(s.schedule)} · 항목 {s.items}
                            </span>
                          </span>
                        </button>
                        <span className="hidden w-[260px] shrink-0 text-right text-[12px] text-text-secondary md:block">
                          {st === "running" ? (
                            <span className="inline-flex items-center gap-1 text-primary">
                              <Loader2 className="size-3.5 animate-spin" aria-hidden />
                              수집 중
                            </span>
                          ) : s.lastRun ? (
                            <>
                              {when(s.lastRun.finishedAt ?? s.lastRun.startedAt)} · {STATUS_KO[st] ?? st}
                              {s.lastRun.new > 0 && ` · 새 ${s.lastRun.new}`}
                              {s.lastRun.failed > 0 && ` · 실패 ${s.lastRun.failed}`}
                            </>
                          ) : (
                            "아직 수집 전"
                          )}
                          {s.nextRunAt && <span className="block text-neutral-400">다음 {when(s.nextRunAt)}</span>}
                        </span>
                        {s.canEdit && (
                          <button
                            type="button"
                            disabled={st === "running"}
                            onClick={() => void run(s)}
                            className="flex h-8 shrink-0 cursor-pointer items-center gap-1 rounded-lg bg-neutral-100 px-2.5 text-[12px] font-semibold text-neutral-700 hover:bg-neutral-200 disabled:opacity-40"
                          >
                            <Play className="size-3.5" aria-hidden />
                            지금 수집
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          ),
        )}
      </div>
      {current && <SourceDrawer src={current} onClose={() => setOpen(null)} onChanged={load} onRun={run} />}
      {adding && (
        <AddSourceDialog
          isAdmin={admin}
          onClose={() => setAdding(false)}
          onCreated={(s) => {
            setAdding(false);
            void load();
            setOpen(s.id);
          }}
        />
      )}
    </div>
  );
}

function SourceDrawer({ src, onClose, onChanged, onRun }: { src: SourceInfo; onClose: () => void; onChanged: () => void; onRun: (s: SourceInfo, asOf?: string) => Promise<void> }) {
  const openSource = useOpenSource();
  const [runs, setRuns] = useState<SourceRunView[]>([]);
  const [items, setItems] = useState<SourceItemView[] | null>(null);
  const [asOf, setAsOf] = useState("");

  const load = useCallback(async () => {
    try {
      const [r, i] = await Promise.all([listSourceRuns(src.id), listSourceItems(src.id)]);
      setRuns(r);
      setItems(i);
    } catch {
      setItems([]);
    }
  }, [src.id]);
  useEffect(() => {
    void load();
  }, [load, src.lastRun?.id, src.lastRun?.status]);

  const toggle = async () => {
    try {
      await updateSource(src.id, { enabled: !src.enabled });
      onChanged();
    } catch (e) {
      toast.error(errText(e, "바꾸지 못했습니다."), { position: "top-center" });
    }
  };
  const remove = async () => {
    if (!window.confirm(`'${src.name}' 소스를 지울까요? 이미 적재한 문서는 그대로 남습니다.`)) return;
    try {
      await deleteSource(src.id);
      onClose();
      onChanged();
    } catch (e) {
      toast.error(errText(e, "지우지 못했습니다."), { position: "top-center" });
    }
  };
  const retry = async (it: SourceItemView) => {
    try {
      await retrySourceItem(it.id);
      toast.success("다시 수집합니다.", { position: "top-center" });
      window.setTimeout(() => {
        onChanged();
        void load();
      }, 1500);
    } catch (e) {
      toast.error(errText(e, "다시 수집하지 못했습니다."), { position: "top-center" });
    }
  };

  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-[520px] max-w-full flex-col bg-white shadow-2xl">
      <div className="flex items-start gap-3 border-b border-neutral-100 px-5 py-4">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[16px] font-bold text-text-primary">{src.name}</p>
          <p className="mt-0.5 text-[12px] text-text-secondary">
            {src.kindKo} · {src.scope === "company" ? "사내 공용" : "워크스페이스"} · {scheduleText(src.schedule)}
          </p>
          {src.watchDir && <p className="mt-1 break-all font-mono text-[11px] text-neutral-500">{src.watchDir}</p>}
          {src.mode === "fixture" && <p className="mt-1 text-[12px] text-amber-700">SEC_USER_AGENT 가 없어 고정 파일(가상)로 모읍니다.</p>}
        </div>
        <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
          <X className="size-5" aria-hidden />
        </button>
      </div>
      {src.canEdit && (
        <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-5 py-3">
          <button type="button" onClick={() => void onRun(src)} className="flex h-8 cursor-pointer items-center gap-1 rounded-lg bg-primary px-3 text-[12px] font-semibold text-white hover:bg-primary-hover">
            <Play className="size-3.5" aria-hidden />
            지금 수집
          </button>
          <span className="flex items-center gap-1 rounded-lg bg-neutral-100 pl-2.5">
            <CalendarClock className="size-3.5 text-neutral-500" aria-hidden />
            <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} aria-label="기준일" className="h-8 bg-transparent text-[12px] outline-none" />
            <button
              type="button"
              disabled={!asOf}
              onClick={() => void onRun(src, asOf)}
              className="h-8 cursor-pointer rounded-r-lg px-2.5 text-[12px] font-semibold text-neutral-700 hover:bg-neutral-200 disabled:opacity-40"
            >
              날짜 지정 수집
            </button>
          </span>
          <span className="flex-1" />
          <button type="button" onClick={() => void toggle()} className="h-8 cursor-pointer rounded-lg px-2.5 text-[12px] text-text-secondary hover:bg-neutral-100">
            {src.enabled ? "예약 끄기" : "예약 켜기"}
          </button>
          <button type="button" onClick={() => void remove()} className="h-8 cursor-pointer rounded-lg px-2.5 text-[12px] text-[#f04452] hover:bg-red-50">
            지우기
          </button>
        </div>
      )}
      <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <h3 className="mb-2 text-[13px] font-semibold text-text-secondary">실행 기록</h3>
        <div className="mb-5 flex flex-col gap-1">
          {runs.length === 0 && <p className="text-[12px] text-text-secondary">아직 없습니다.</p>}
          {runs.slice(0, 6).map((r) => (
            <div key={r.id} className="flex items-center gap-2 text-[12px]">
              <span className="w-[92px] shrink-0 text-text-secondary">{when(r.startedAt)}</span>
              <span className="w-[64px] shrink-0 font-medium text-text-primary">{STATUS_KO[r.status] ?? r.status}</span>
              <span className="min-w-0 flex-1 truncate text-text-secondary">
                {r.trigger === "replay" ? `${r.asOf} 기준 · ` : r.trigger === "schedule" ? "예약 · " : ""}새 {r.new} · 실패 {r.failed}
                {r.note && ` · ${r.note}`}
              </span>
            </div>
          ))}
        </div>
        <h3 className="mb-2 text-[13px] font-semibold text-text-secondary">모은 항목</h3>
        {items === null && <p className="text-[12px] text-text-secondary">불러오는 중…</p>}
        {items?.length === 0 && <p className="text-[12px] text-text-secondary">아직 없습니다.</p>}
        <div className="flex flex-col">
          {items?.map((it) => (
            <div key={it.id} className="flex items-start gap-2 border-b border-neutral-100 py-2 last:border-0">
              <div className="min-w-0 flex-1">
                {it.docId ? (
                  <button type="button" onClick={() => openSource(it.docId!)} className="block w-full cursor-pointer truncate text-left text-[13px] font-medium text-text-primary hover:text-primary">
                    {it.title || it.key}
                  </button>
                ) : (
                  <span className="block truncate text-[13px] font-medium text-text-primary">{it.title || it.key}</span>
                )}
                <span className="block truncate text-[11px] text-text-secondary">
                  {[it.publishedAt, it.status === "error" ? `실패: ${it.error ?? ""}` : null, host(it.url)].filter(Boolean).join(" · ")}
                </span>
              </div>
              {it.status === "error" && src.canEdit && (
                <button type="button" onClick={() => void retry(it)} className="flex h-7 shrink-0 cursor-pointer items-center gap-1 rounded-md bg-neutral-100 px-2 text-[11px] font-semibold text-neutral-700 hover:bg-neutral-200">
                  <RotateCcw className="size-3" aria-hidden />
                  재처리
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
