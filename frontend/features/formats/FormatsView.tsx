"use client";

/**
 * 문서 양식 — 찾기(이름·설명·섹션) + 보기 셋: 최근 사용(기본 — 내가 최근에 쓴 양식이 먼저) · 워크스페이스 · 사내(많이 쓴 양식이 먼저).
 * 사내 = 기본 양식(코드) + 사내로 등록한 것, 워크스페이스 = 이 워크스페이스에 등록한 것. 줄을 누르면 양식 보기(예시 문서·[이 양식으로 쓰기]),
 * 고치기·지우기는 만든 사람이나 관리자만. [새 양식] = 샘플을 올리면 AI 가 분석하고, 끝나면 '등록 전' 양식이 양식 화면으로 열린다(NewFormatDialog, 빈 양식으로도 시작) —
 * 원본과 비교해 고치고(직접·말로) 등록한다. 등록 전 양식은 만든 사람의 목록 맨 위에만 보인다.
 * 표·차트 양식 탭은 FEATURES.tableFormats(끔) — 코드는 그대로.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { FilePlus2, FileText, LayoutTemplate, Paperclip, Search, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError } from "../report/api";
import { deleteReportType, deleteTemplate, listTemplates, patchTemplate } from "../research/api";
import { TemplateDialog } from "../research/TemplateDialog";
import type { ResearchTemplate } from "../research/types";
import { PageHeader } from "../workspace/components/views/PageHeader";
import { useWorkspace } from "../workspace/context";
import { FEATURES } from "../workspace/features";
import { createFormat, listFormats } from "./api";
import { FormatEditor, SCOPE_LABEL } from "./FormatEditor";
import { NewFormatDialog } from "./NewFormatDialog";
import type { DocFormat } from "./types";

const TPL_SCOPE: Record<string, string> = { company: "사내", workspace: "워크스페이스", user: "나만" };
const SUBJECT_LABEL: Record<string, string> = { company: "기업", document: "문서", period: "기간", label: "항목" };
type View = "recent" | "workspace" | "company";
const VIEWS: { id: View; label: string }[] = [
  { id: "recent", label: "최근 사용" },
  { id: "workspace", label: "워크스페이스" },
  { id: "company", label: "사내" },
];

function errText(e: unknown, fallback: string): string {
  return e instanceof ApiError && e.status < 500 ? e.message : fallback;
}

function counts(f: DocFormat): string {
  const slots = [...f.sections.flatMap((s) => s.slots), ...(f.assets ?? [])];
  const t = slots.filter((x) => x.kind === "table").length;
  const c = slots.filter((x) => x.kind === "chart").length;
  return [`섹션 ${f.sections.length}`, t && `표 ${t}`, c && `차트 ${c}`].filter(Boolean).join(" · ");
}

function day(iso?: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("ko-KR", { month: "numeric", day: "numeric" }) : "";
}

/** 등록 전(내 것)이 맨 위, 그다음 최근 사용 = 내가 마지막으로 쓴 때 → 사용 수 → 이름, 워크스페이스·사내 = 사용 수 → 최근 → 이름 */
function sorted(list: DocFormat[], view: View): DocFormat[] {
  const t = (f: DocFormat) => (f.lastUsed ? Date.parse(f.lastUsed) : 0);
  return [...list].sort((a, b) => Number(!!b.draft) - Number(!!a.draft) || (view === "recent" ? t(b) - t(a) || (b.uses ?? 0) - (a.uses ?? 0) : (b.uses ?? 0) - (a.uses ?? 0) || t(b) - t(a)) || a.title.localeCompare(b.title, "ko"));
}

export function FormatsView() {
  const ws = useWorkspace();
  const [tab, setTab] = useState<"docs" | "tables">("docs");
  const [formats, setFormats] = useState<DocFormat[] | null>(null);
  const [templates, setTemplates] = useState<ResearchTemplate[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [editTpl, setEditTpl] = useState<ResearchTemplate | null>(null);
  const [adding, setAdding] = useState(false);
  const [view, setView] = useState<View>("recent");
  const [q, setQ] = useState("");

  const load = useCallback(async () => {
    try {
      const [fs, ts] = await Promise.all([listFormats(ws.workspaceId), listTemplates(ws.workspaceId)]);
      setFormats(fs);
      setTemplates(ts);
    } catch {
      setFormats([]);
    }
  }, [ws.workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  // 문서 양식이 바뀌면 새 문서·양식 고르기 목록(meta.reportTypes)도
  const changed = async (open?: string) => {
    await Promise.all([load(), ws.refreshTypes()]);
    if (open) setOpenId(open);
  };

  const createBlank = async () => {
    try {
      const f = await createFormat(ws.workspaceId, {});
      setAdding(false);
      await changed(f.id);
    } catch (e) {
      toast.error(errText(e, "만들지 못했습니다."), { position: "top-center" });
    }
  };

  // 샘플 분석이 끝나 등록 전 양식이 생기면 — 창을 닫고 그 양식을 양식 화면으로
  const refreshTypes = ws.refreshTypes;
  const opened = useCallback(
    (id: string) => {
      setAdding(false);
      void Promise.all([load(), refreshTypes()]).then(() => setOpenId(id));
    },
    [load, refreshTypes],
  );

  const remove = async (f: DocFormat) => {
    if (!window.confirm(`문서 양식 '${f.title}' 을 지울까요? 이 양식으로 만든 문서는 그대로 남습니다.`)) return;
    try {
      await deleteReportType(f.id);
      await changed();
    } catch (e) {
      toast.error(errText(e, "지우지 못했습니다."), { position: "top-center" });
    }
  };

  const shown = useMemo(() => {
    const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const hit = (f: DocFormat) => {
      const text = [f.title, f.desc, f.sample, ...f.sections.map((s) => s.title)].join(" ").toLowerCase();
      return words.every((w) => text.includes(w));
    };
    const inView = (f: DocFormat) => (view === "recent" ? true : view === "company" ? f.scope === "builtin" || f.scope === "company" : f.scope === "workspace" || f.scope === "user");
    return sorted((formats ?? []).filter((f) => inView(f) && hit(f)), view);
  }, [formats, q, view]);

  const open = formats?.find((f) => f.id === openId);
  if (open) {
    return (
      <FormatEditor
        key={open.id}
        format={open}
        templates={templates}
        onBack={() => setOpenId(null)}
        onSaved={(f) => {
          setFormats((xs) => (xs ?? []).map((x) => (x.id === f.id ? { ...x, ...f } : x)));
          void ws.refreshTypes();
        }}
        onRemoved={() => {
          setOpenId(null);
          void changed();
        }}
      />
    );
  }

  const canRemoveTpl = (t: ResearchTemplate) => !t.builtin && (t.scope === "workspace" ? ws.can("editor") : t.ownerId === ws.me.id);
  const removeTpl = async (t: ResearchTemplate) => {
    if (!window.confirm(`양식 '${t.name}' 을 지울까요? 문서 양식의 자리에 쓰였다면 그 자리는 비게 됩니다.`)) return;
    try {
      await deleteTemplate(t.id);
      setTemplates((xs) => xs.filter((x) => x.id !== t.id));
    } catch (e) {
      toast.error(errText(e, "지우지 못했습니다."), { position: "top-center" });
    }
  };

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
      <PageHeader
        title="문서 양식"
        actions={
          tab === "docs" &&
          ws.can("editor") && (
            <button type="button" onClick={() => setAdding(true)} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover">
              <FilePlus2 className="size-4" aria-hidden />새 양식
            </button>
          )
        }
      />
      <div className="mx-auto max-w-[960px] px-8 pb-14">
        {FEATURES.tableFormats && (
          <div className="mb-4 flex items-center gap-1 border-b border-neutral-200">
            {(["docs", "tables"] as const).map((t) => (
              <button key={t} type="button" onClick={() => setTab(t)} className={cn("-mb-px cursor-pointer border-b-2 px-3 py-2 text-[15px] font-semibold", tab === t ? "border-neutral-900 text-text-primary" : "border-transparent text-neutral-500 hover:text-neutral-800")}>
                {t === "docs" ? "문서 양식" : "표·차트 양식"}
              </button>
            ))}
          </div>
        )}

        {tab === "docs" && (
          <>
            <label className="flex h-11 items-center gap-2 rounded-xl bg-white px-3.5 focus-within:ring-2 focus-within:ring-primary/30">
              <Search className="size-4 text-neutral-500" aria-hidden />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="양식 이름·설명·섹션으로 찾기" className="min-w-0 flex-1 bg-transparent text-[14px] outline-none" />
              {q && (
                <button type="button" aria-label="지우기" onClick={() => setQ("")} className="cursor-pointer rounded p-0.5 text-neutral-400 hover:text-neutral-700">
                  <X className="size-4" aria-hidden />
                </button>
              )}
            </label>
            <div className="mt-3 flex items-center gap-1.5">
              {VIEWS.map((v) => (
                <button key={v.id} type="button" aria-pressed={view === v.id} onClick={() => setView(v.id)} className={cn("h-8 cursor-pointer rounded-full px-3 text-[13px] font-medium transition-colors", view === v.id ? "bg-neutral-900 text-white" : "bg-white text-neutral-700 hover:bg-neutral-200")}>
                  {v.label}
                </button>
              ))}
              <span className="ml-2 text-[12px] text-text-secondary">{view === "recent" ? "내가 최근에 쓴 양식부터" : "많이 쓴 양식부터"}</span>
            </div>

            <section className="mt-3 rounded-[24px] bg-white px-3 py-2">
              {formats === null && <p className="px-2 py-6 text-[15px] text-neutral-500">불러오는 중…</p>}
              {formats && shown.length === 0 && <p className="px-2 py-10 text-center text-[14px] text-neutral-500">{q ? "찾는 양식이 없어요" : view === "workspace" ? "이 워크스페이스에 등록한 양식이 없어요 — [새 양식]으로 샘플을 올려 만드세요" : "양식이 없어요"}</p>}
              {shown.map((f) => (
                <div key={f.id} className="group flex items-center gap-1 rounded-xl hover:bg-neutral-50">
                  <button type="button" onClick={() => setOpenId(f.id)} className="flex min-w-0 flex-1 cursor-pointer items-center gap-3.5 px-2 py-2.5 text-left">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary">
                      <FileText className="size-[18px]" aria-hidden />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate text-[15px] font-semibold text-text-primary">{f.title}</span>
                        {f.draft ? (
                          <span className="shrink-0 rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-semibold text-amber-700">등록 전</span>
                        ) : (
                          <span className="shrink-0 rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] font-medium text-neutral-500">{SCOPE_LABEL[f.scope]}</span>
                        )}
                        {f.hasSample && <Paperclip className="size-3.5 shrink-0 text-neutral-400" aria-label="예시 문서 있음" />}
                      </span>
                      <span className="block truncate text-[13px] text-neutral-500">
                        {[f.uses ? `${f.uses}번 사용` : "아직 안 씀", f.lastUsed && `최근 ${day(f.lastUsed)}`, counts(f), f.ownerId && f.ownerId !== ws.me.id ? f.owner : null].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                  </button>
                  {f.editable && (
                    <button type="button" title="양식 지우기" aria-label="양식 지우기" onClick={() => void remove(f)} className="mr-2 cursor-pointer rounded-lg p-1.5 text-neutral-400 opacity-0 group-hover:opacity-100 hover:bg-neutral-100 hover:text-red-600">
                      <Trash2 className="size-4" aria-hidden />
                    </button>
                  )}
                </div>
              ))}
            </section>
          </>
        )}

        {tab === "tables" && formats && (
          <section className="mt-4 rounded-[24px] bg-white px-3 py-2">
            {templates.map((t) => (
              <div key={t.id} className="group flex items-center gap-1 rounded-xl hover:bg-neutral-50">
                <button type="button" disabled={t.builtin || !canRemoveTpl(t)} onClick={() => setEditTpl(t)} className="flex min-w-0 flex-1 cursor-pointer items-center gap-3.5 px-2 py-2.5 text-left disabled:cursor-default">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-neutral-100 text-neutral-600">
                    <LayoutTemplate className="size-[18px]" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px] font-semibold text-text-primary">{t.name}</span>
                    <span className="block truncate text-[13px] text-neutral-500">
                      {[t.builtin ? "기본" : TPL_SCOPE[t.scope], t.spec.chart ? (t.spec.chart.type === "line" ? "꺾은선 차트" : "막대 차트") : null, `행: ${SUBJECT_LABEL[t.spec.subject.kind] ?? t.spec.subject.label}${t.spec.rows ? ` ${t.spec.rows.length}개 고정` : ""}`, t.spec.itemsOpen ? "열은 매번" : `열 ${t.spec.items.filter((i) => !i.hidden).length}개`, t.owner && !t.builtin ? t.owner : null].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </button>
                {canRemoveTpl(t) && (
                  <button type="button" title="양식 지우기" aria-label="양식 지우기" onClick={() => void removeTpl(t)} className="mr-2 cursor-pointer rounded-lg p-1.5 text-neutral-400 opacity-0 group-hover:opacity-100 hover:bg-neutral-100 hover:text-red-600">
                    <Trash2 className="size-4" aria-hidden />
                  </button>
                )}
              </div>
            ))}
          </section>
        )}
      </div>

      {editTpl && (
        <TemplateDialog
          heading="표·차트 양식 고치기"
          edit
          table={{ title: editTpl.name, templateId: editTpl.id, spec: { name: editTpl.spec.name, subject: editTpl.spec.subject, orientation: editTpl.spec.orientation, itemsOpen: editTpl.spec.itemsOpen }, items: editTpl.spec.items, subjects: editTpl.spec.rows ?? [] }}
          onClose={() => setEditTpl(null)}
          onSubmit={async ({ name, spec }) => {
            // 차트 양식은 고친 열 이름으로 계열을 다시 잇는다. 실패는 대화상자가 알린다
            const chart = editTpl.spec.chart ? { ...editTpl.spec.chart, seriesLabels: (spec.items ?? []).filter((i) => !i.hidden && i.type !== "text").map((i) => i.label) } : undefined;
            const t = await patchTemplate(editTpl.id, { name, spec: { ...spec, ...(chart ? { chart } : {}) } });
            setTemplates((xs) => xs.map((x) => (x.id === t.id ? t : x)));
            toast.success("양식을 저장했습니다.", { position: "top-center" });
          }}
        />
      )}

      {adding && <NewFormatDialog onClose={() => setAdding(false)} onBlank={() => createBlank()} onReady={opened} />}
    </div>
  );
}
