"use client";

/**
 * 드라이브 ▸ 에셋 — 리서치로 만든 표·차트. 만든 것은 자동으로 '내 에셋'(나만), 공유하면 멤버가 본다.
 * 검색창 하나가 낱말·종류(표·차트)·범위(내 것·공유)·날짜(오늘·지난주·최근 7일…)를 함께 읽는다(BE research/assets.py — AI 의 찾기와 같은 규칙).
 * 줄을 누르면 오른쪽 미리보기 — AI 작업에서 열기 · 공유 · 내려받기 · 지우기. [양식] 탭은 표 양식 목록.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BarChart3, Download, ExternalLink, FileText, FolderCheck, FolderPlus, LayoutTemplate, LineChart, Loader2, NotebookPen, Search, Table2, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError, downloadFile } from "../../../report/api";
import { shapeOf } from "../../../report/components/assets/AssetPanel";
import { AssetBlockView } from "../../../report/components/report/FormatBlock";
import { deleteReportType, deleteTable, deleteTemplate, getTable, listAssets, listTemplates, patchTable, tableExportPath } from "../../../research/api";
import type { AssetItem, ResearchTable, ResearchTemplate } from "../../../research/types";
import { createReport } from "../../api";
import { useWorkspace } from "../../context";
import { PageHeader } from "./PageHeader";

type Kind = "" | "table" | "chart" | "note";
type Scope = "" | "mine" | "shared";
const SCOPE_LABEL: Record<string, string> = { company: "사내", workspace: "워크스페이스", user: "나만" };
const SUBJECT_LABEL: Record<string, string> = { company: "기업", document: "문서", period: "기간", label: "항목" };

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick} className={cn("h-8 cursor-pointer rounded-full px-3 text-[13px] font-medium transition-colors", on ? "bg-neutral-900 text-white" : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200")}>
      {children}
    </button>
  );
}

function iconOf(a: { kind: string; chartType?: string }) {
  return a.kind === "note" ? NotebookPen : a.kind === "chart" ? (a.chartType === "line" ? LineChart : BarChart3) : Table2;
}

function day(iso: string): string {
  return new Date(iso).toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
}

export function AssetsView({ initialOpen = null }: { initialOpen?: string | null }) {
  const ws = useWorkspace();
  const [tab, setTab] = useState<"assets" | "templates">("assets");
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<Kind>("");
  const [scope, setScope] = useState<Scope>("");
  const [items, setItems] = useState<AssetItem[] | null>(null);
  const [cond, setCond] = useState<string[]>([]);
  const [openId, setOpenId] = useState<string | null>(initialOpen);
  const [templates, setTemplates] = useState<ResearchTemplate[] | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await listAssets(ws.workspaceId, q.trim(), kind || undefined, scope || undefined);
      setItems(r.assets);
      // 검색어에서 읽은 조건(칩으로 고르지 않은 것만) — '지난주 · 표' 처럼
      const qk = r.query;
      setCond([qk.dateLabel, !kind && qk.kind ? ({ chart: "차트", note: "메모" } as Record<string, string>)[qk.kind] ?? "표" : null, !scope && qk.scope ? (qk.scope === "mine" ? "내 것" : "공유") : null].filter((x): x is string => Boolean(x)));
    } catch {
      setItems([]);
    }
  }, [kind, q, scope, ws.workspaceId]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 200);
    return () => clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (tab !== "templates" || templates) return;
    void listTemplates(ws.workspaceId)
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, [tab, templates, ws.workspaceId]);

  const removeTemplate = async (t: ResearchTemplate) => {
    if (!window.confirm(`양식 '${t.name}' 을 지울까요?`)) return;
    try {
      await deleteTemplate(t.id);
      setTemplates((xs) => (xs ?? []).filter((x) => x.id !== t.id));
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "지우지 못했습니다.", { position: "top-center" });
    }
  };
  const canRemove = (t: ResearchTemplate) => !t.builtin && (t.scope === "workspace" ? ws.can("editor") : t.ownerId === ws.me.id);
  // 샘플에서 등록한 리포트 양식(rt:) — 새 문서·문서 작성에서 고른다
  const formats = ws.meta.reportTypes.filter((t) => t.kind === "registered");
  const removeFormat = async (id: string, name: string) => {
    if (!window.confirm(`리포트 양식 '${name}' 을 지울까요? 이 양식으로 만든 문서는 그대로 남습니다.`)) return;
    try {
      await deleteReportType(id);
      await ws.refreshTypes();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "지우지 못했습니다.", { position: "top-center" });
    }
  };

  return (
    <div className="flex min-h-0 flex-1">
      <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
        <PageHeader title="에셋" />
        <div className="mx-auto max-w-[960px] px-8 pb-14">
          <div className="flex items-center gap-1 border-b border-neutral-200">
            {(["assets", "templates"] as const).map((t) => (
              <button key={t} type="button" onClick={() => setTab(t)} className={cn("-mb-px cursor-pointer border-b-2 px-3 py-2 text-[15px] font-semibold", tab === t ? "border-neutral-900 text-text-primary" : "border-transparent text-neutral-500 hover:text-neutral-800")}>
                {t === "assets" ? "표·차트" : "양식"}
              </button>
            ))}
          </div>

          {tab === "assets" ? (
            <>
              <label className="mt-4 flex h-11 items-center gap-2 rounded-xl bg-white px-3.5 focus-within:ring-2 focus-within:ring-primary/30">
                <Search className="size-4 text-neutral-500" aria-hidden />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="제목·기업·항목·기간으로 찾기 (예: 지난주 Peer 표)" className="min-w-0 flex-1 bg-transparent text-[14px] outline-none" />
                {q && (
                  <button type="button" aria-label="지우기" onClick={() => setQ("")} className="cursor-pointer rounded p-0.5 text-neutral-400 hover:text-neutral-700">
                    <X className="size-4" aria-hidden />
                  </button>
                )}
              </label>
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <Chip on={kind === ""} onClick={() => setKind("")}>
                  전체
                </Chip>
                <Chip on={kind === "table"} onClick={() => setKind("table")}>
                  표
                </Chip>
                <Chip on={kind === "chart"} onClick={() => setKind("chart")}>
                  차트
                </Chip>
                <Chip on={kind === "note"} onClick={() => setKind("note")}>
                  메모
                </Chip>
                <span className="mx-1.5 h-4 w-px bg-neutral-300" />
                <Chip on={scope === ""} onClick={() => setScope("")}>
                  모두
                </Chip>
                <Chip on={scope === "mine"} onClick={() => setScope("mine")}>
                  내 것
                </Chip>
                <Chip on={scope === "shared"} onClick={() => setScope("shared")}>
                  공유됨
                </Chip>
                {cond.length > 0 && <span className="ml-2 text-[13px] text-text-secondary">{cond.join(" · ")}</span>}
              </div>

              <section className="mt-4 rounded-[24px] bg-white px-3 py-2">
                {items === null && <p className="px-2 py-6 text-[15px] text-neutral-500">불러오는 중…</p>}
                {items?.length === 0 && <p className="px-2 py-10 text-center text-[15px] text-neutral-500">{q || kind || scope ? "찾는 에셋이 없어요" : "AI 작업에서 만든 표·차트·메모, 자료에서 꺼낸 표가 여기 쌓여요"}</p>}
                {items?.map((a) => {
                  const Icon = iconOf(a);
                  return (
                    <button
                      key={a.id}
                      type="button"
                      onClick={() => setOpenId(a.id)}
                      className={cn("flex w-full cursor-pointer items-center gap-3.5 rounded-xl px-2 py-2.5 text-left transition-colors", openId === a.id ? "bg-primary-soft" : "hover:bg-neutral-50")}
                    >
                      <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl", a.kind === "chart" ? "bg-amber-50 text-amber-600" : a.kind === "note" ? "bg-emerald-50 text-emerald-600" : "bg-primary-soft text-primary")}>
                        <Icon className="size-[18px]" aria-hidden />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[15px] font-semibold text-text-primary">{a.title}</span>
                        <span className="block truncate text-[13px] text-neutral-500">
                          {[a.period && `${a.period} 기준`, a.kind === "note" ? `메모 · 출처 ${a.cites ?? 0}` : a.kind === "chart" ? (a.sourceTitle ? `원 표: ${a.sourceTitle}` : "차트") : `${a.rows}행 × ${a.cols}열`, a.sourceDoc && `자료: ${a.sourceDoc}`, !a.mine && a.createdBy].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                      {a.saved && (
                        <span className="flex shrink-0 items-center gap-1 text-[12px] text-primary">
                          <FolderCheck className="size-3.5" aria-hidden />
                          공유됨
                        </span>
                      )}
                      <span className="w-16 shrink-0 text-right text-[12px] text-neutral-500">{day(a.updatedAt)}</span>
                    </button>
                  );
                })}
              </section>
            </>
          ) : (
            <>
            {formats.length > 0 && (
              <>
                <p className="mt-5 px-1 text-[13px] font-semibold text-neutral-600">리포트 양식</p>
                <section className="mt-2 rounded-[24px] bg-white px-3 py-2">
                  {formats.map((f) => (
                    <div key={f.id} className="group flex items-center gap-3.5 rounded-xl px-2 py-2.5 hover:bg-neutral-50">
                      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary">
                        <FileText className="size-[18px]" aria-hidden />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[15px] font-semibold text-text-primary">{f.title}</span>
                        <span className="block truncate text-[13px] text-neutral-500">{[f.scope && SCOPE_LABEL[f.scope], `섹션 ${f.items.length}`, `표 ${f.tables ?? 0} · 차트 ${f.charts ?? 0}`, f.ownerId !== ws.me.id ? f.owner : null].filter(Boolean).join(" · ")}</span>
                      </span>
                      {(f.scope === "workspace" ? ws.can("editor") : f.ownerId === ws.me.id) && (
                        <button type="button" title="양식 지우기" aria-label="양식 지우기" onClick={() => void removeFormat(f.id, f.title)} className="cursor-pointer rounded-lg p-1.5 text-neutral-400 opacity-0 group-hover:opacity-100 hover:bg-neutral-100 hover:text-red-600">
                          <Trash2 className="size-4" aria-hidden />
                        </button>
                      )}
                    </div>
                  ))}
                </section>
                <p className="mt-5 px-1 text-[13px] font-semibold text-neutral-600">표·차트 양식</p>
              </>
            )}
            <section className="mt-4 rounded-[24px] bg-white px-3 py-2">
              {templates === null && <p className="px-2 py-6 text-[15px] text-neutral-500">불러오는 중…</p>}
              {templates?.map((t) => (
                <div key={t.id} className="group flex items-center gap-3.5 rounded-xl px-2 py-2.5 hover:bg-neutral-50">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-neutral-100 text-neutral-600">
                    <LayoutTemplate className="size-[18px]" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px] font-semibold text-text-primary">{t.name}</span>
                    <span className="block truncate text-[13px] text-neutral-500">
                      {[SCOPE_LABEL[t.scope], `행: ${SUBJECT_LABEL[t.spec.subject.kind] ?? t.spec.subject.label}${t.spec.rows ? ` ${t.spec.rows.length}개 고정` : ""}`, t.spec.itemsOpen ? "열은 매번" : `열 ${t.spec.items.filter((i) => !i.hidden).length}개`, t.owner && !t.builtin ? t.owner : null].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  {canRemove(t) && (
                    <button type="button" title="양식 지우기" aria-label="양식 지우기" onClick={() => void removeTemplate(t)} className="cursor-pointer rounded-lg p-1.5 text-neutral-400 opacity-0 group-hover:opacity-100 hover:bg-neutral-100 hover:text-red-600">
                      <Trash2 className="size-4" aria-hidden />
                    </button>
                  )}
                </div>
              ))}
            </section>
            </>
          )}
        </div>
      </div>
      {openId && (
        <AssetDrawer
          key={openId}
          id={openId}
          onClose={() => setOpenId(null)}
          onChanged={(t) => setItems((xs) => (xs ?? []).map((x) => (x.id === t.id ? { ...x, saved: t.saved, title: t.title } : x)))}
          onRemoved={(id) => {
            setOpenId(null);
            setItems((xs) => (xs ?? []).filter((x) => x.id !== id));
          }}
          taskId={items?.find((x) => x.id === openId)?.taskId ?? null}
        />
      )}
    </div>
  );
}

/** 표·차트·메모 미리보기 서랍 — 에셋 화면, 드라이브·검색의 '정리한 데이터'(남이 저장한 것)에서 쓴다. className 으로 폭을 바꾼다 */
export function AssetDrawer({ id, taskId, onClose, onChanged, onRemoved, className }: { id: string; taskId: string | null; onClose: () => void; onChanged: (t: ResearchTable) => void; onRemoved: (id: string) => void; className?: string }) {
  const ws = useWorkspace();
  const [t, setT] = useState<ResearchTable | null>(null);
  const [busy, setBusy] = useState(false);
  const [dl, setDl] = useState(false);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    void getTable(id)
      .then(setT)
      .catch(() => {
        toast.error("열지 못했습니다.", { position: "top-center" });
        closeRef.current();
      });
  }, [id]);

  const run = async (fn: () => Promise<void>, fail: string) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : fail, { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  // 만든 내 작업이 있으면 거기서, 없으면(남의 에셋·지운 작업) 새 작업을 만들어 결과에 둔다
  const openInTask = () =>
    run(async () => {
      const sid = taskId ?? (await createReport(ws.workspaceId, { reportType: "free" })).session.id;
      ws.nav.openReport(sid, id);
    }, "열지 못했습니다.");

  const meta = useMemo(() => {
    if (!t) return "";
    const shape = t.kind === "note" ? "메모" : t.kind === "chart" ? (t.chart?.sourceTitle ? `원 표: ${t.chart.sourceTitle}` : "") : shapeOf(t);
    return [t.period && `${t.period.label} 기준`, shape, t.createdBy, day(t.updatedAt)].filter(Boolean).join(" · ");
  }, [t]);

  return (
    <aside className={cn("flex w-[520px] shrink-0 flex-col border-l border-neutral-200 bg-white", className)}>
      <div className="flex items-start justify-between gap-2 px-5 pt-5">
        <div className="min-w-0">
          <h2 className="text-[18px] leading-snug font-bold tracking-tight text-text-primary">{t?.title ?? "…"}</h2>
          <p className="mt-1 truncate text-[12px] text-text-secondary">{meta}</p>
        </div>
        <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
          <X className="size-5" aria-hidden />
        </button>
      </div>
      {!t ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="size-5 animate-spin text-neutral-400" aria-hidden />
        </div>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap gap-1.5 px-5">
            {ws.can("editor") && (
              <button type="button" disabled={busy} onClick={() => void openInTask()} className="flex h-9 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-3.5 text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
                <ExternalLink className="size-4" aria-hidden />
                AI 작업에서 열기
              </button>
            )}
            {t.mine && (
              <button
                type="button"
                disabled={busy || t.status === "running"}
                onClick={() =>
                  void run(async () => {
                    const next = await patchTable(t.id, { saved: !t.saved });
                    setT(next);
                    onChanged(next);
                  }, "바꾸지 못했습니다.")
                }
                className="flex h-9 cursor-pointer items-center gap-1.5 rounded-xl bg-neutral-100 px-3.5 text-[13px] font-semibold text-neutral-700 hover:bg-neutral-200 disabled:opacity-50"
              >
                {t.saved ? <FolderCheck className="size-4 text-primary" aria-hidden /> : <FolderPlus className="size-4" aria-hidden />}
                {t.saved ? "드라이브에서 빼기" : "드라이브에 저장"}
              </button>
            )}
            <div className="relative">
              <button type="button" disabled={t.status !== "done"} onClick={() => setDl((v) => !v)} aria-label="내려받기" title="내려받기" className="flex h-9 cursor-pointer items-center rounded-xl bg-neutral-100 px-3 text-neutral-700 hover:bg-neutral-200 disabled:opacity-50">
                <Download className="size-4" aria-hidden />
              </button>
              {dl && (
                <div className="absolute top-full left-0 z-30 mt-1 w-44 rounded-2xl bg-white p-1.5 shadow-[0_8px_24px_rgba(0,27,55,0.14)]" onMouseLeave={() => setDl(false)}>
                  {(t.kind === "note" ? (["docx"] as const) : (["docx", "xlsx"] as const)).map((fmt) => (
                    <button
                      key={fmt}
                      type="button"
                      onClick={() => {
                        setDl(false);
                        void run(() => downloadFile(tableExportPath(t.id, fmt), `${t.title}.${fmt}`), "내려받지 못했습니다.");
                      }}
                      className="flex w-full cursor-pointer rounded-xl px-3 py-2 text-left text-[13px] font-medium text-text-primary hover:bg-neutral-100"
                    >
                      {fmt === "docx" ? "Word (DOCX)" : "Excel (XLSX)"}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {t.mine && (
              <button
                type="button"
                title="지우기"
                aria-label="지우기"
                disabled={busy}
                onClick={() => window.confirm("이 에셋을 지울까요? 문서에 넣은 복사본은 그대로 남습니다.") && void run(async () => (await deleteTable(t.id), onRemoved(t.id)), "지우지 못했습니다.")}
                className="ml-auto flex h-9 cursor-pointer items-center rounded-xl px-3 text-neutral-500 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
              >
                <Trash2 className="size-4" aria-hidden />
              </button>
            )}
          </div>
          <div className="thin-scrollbar mt-2 min-h-0 flex-1 overflow-y-auto px-5 pb-8">
            <AssetBlockView block={t.block} caption={false} />
          </div>
        </>
      )}
    </aside>
  );
}
