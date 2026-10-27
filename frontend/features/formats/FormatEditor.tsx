"use client";

/**
 * 문서 양식 보기·고치기. 가운데 [예시 문서] = 문서 틀(문체·섹션·작성 안내 — 대상과 무관한 꼴), [에셋] = 샘플에서 뽑은 표·차트 양식(빈 틀 미리보기).
 * 오른쪽은 원본 — 예시 문서 탭이면 올린 샘플 전체, 에셋 탭이면 고른 표·차트가 샘플에서 있던 부분만(분석 때 받은 위치로 잘라 낸 그림).
 * 고치기는 만든 사람이나 관리자(워크스페이스 소유자)만. 에셋은 이름·설명·빼기·차트 종류만(그 밖 구성·겉모양은 샘플에서 온 것).
 * [이 양식으로 쓰기] = 이 양식으로 새 AI 작업을 만들고 문서 작성 모드로 연다. 고쳐도 이미 만든 문서는 그대로(새 문서부터 이 양식).
 * 등록 전 양식(샘플 분석 직후 — 만든 사람에게만 보임)은 [버리기]·[등록] — 등록해야 다른 사람·새 문서에 보인다.
 * 고칠 수 있는 양식은 아래 입력창으로 AI 에게 말로 고쳐 달라고 할 수 있다(고친 것은 바로 저장 — 직접 고친 것이 있으면 먼저 저장).
 * 옛 양식(기본·표 양식 자리)은 섹션 뒤 자리(slots)를 그대로 보인다.
 */
import { useMemo, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowUp, BarChart3, ExternalLink, FileText, ImageIcon, Loader2, PenLine, Plus, Send, Sparkles, Table2, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError, patchSession } from "../report/api";
import { deleteReportType } from "../research/api";
import type { ResearchTemplate, TemplateScope } from "../research/types";
import { createReport } from "../workspace/api";
import { useWorkspace } from "../workspace/context";
import { formatAssetImageUrl, formatSampleUrl, patchFormat, registerFormat, reviseFormat } from "./api";
import { AssetFormView } from "./AssetFormView";
import { SlotPreview } from "./SlotPreview";
import type { DocFormat, FormatAsset, FormatSection, FormatSlot } from "./types";

const LEVELS = [
  { v: 1, label: "큰 제목" },
  { v: 2, label: "중간 제목" },
  { v: 3, label: "작은 제목" },
];
export const SCOPE_LABEL: Record<string, string> = { builtin: "사내 · 기본", company: "사내", workspace: "워크스페이스", user: "워크스페이스" };
const CHART_LABEL: Record<string, string> = { line: "선", bar: "막대", barh: "가로 막대", area: "영역", pie: "원", combo: "막대+선", band: "밴드", other: "차트" };
const field = "rounded-lg bg-neutral-100 px-2.5 text-[13px] outline-none focus:bg-white focus:ring-2 focus:ring-primary/30 disabled:bg-transparent disabled:px-0";

function slotIcon(s: FormatSlot) {
  return s.kind === "figure" ? ImageIcon : s.kind === "chart" ? BarChart3 : Table2;
}

/** 같은 종류 안에서의 번호(표 1·표 2…) */
function numbering(assets: FormatAsset[]): Map<string, number> {
  const seen = { table: 0, chart: 0 };
  return new Map(assets.map((a) => [a.id, ++seen[a.kind]]));
}

/** 이 양식으로 새 AI 작업(문서 작성 모드) */
export function useStartWithFormat() {
  const ws = useWorkspace();
  const [busy, setBusy] = useState(false);
  const start = async (id: string) => {
    setBusy(true);
    try {
      const p = await createReport(ws.workspaceId, { reportType: id });
      await patchSession(p.session.id, { modes: { research: false, writing: true } });
      ws.nav.openReport(p.session.id);
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "작업을 만들지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };
  return { start, busy };
}

function errText(e: unknown, fallback: string): string {
  return e instanceof ApiError && e.status < 500 ? e.message : fallback;
}

export function FormatEditor({ format, templates, onBack, onSaved, onRemoved }: { format: DocFormat; templates: ResearchTemplate[]; onBack: () => void; onSaved: (f: DocFormat) => void; onRemoved: () => void }) {
  const ws = useWorkspace();
  const ro = !format.editable;
  const [name, setName] = useState(format.title);
  const [desc, setDesc] = useState(format.desc);
  const [style, setStyle] = useState(format.style ?? "");
  const [scope, setScope] = useState(format.scope);
  const [sections, setSections] = useState<FormatSection[]>(format.sections);
  const [assets, setAssets] = useState<FormatAsset[]>(format.assets ?? []);
  const [tab, setTab] = useState<"doc" | "assets">("doc");
  const [selId, setSelId] = useState<string | null>(format.assets?.[0]?.id ?? null);
  const [openSlot, setOpenSlot] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState("");
  const [revising, setRevising] = useState(false);
  const [note, setNote] = useState("");
  const starter = useStartWithFormat();
  const byId = useMemo(() => new Map(templates.map((t) => [t.id, t])), [templates]);
  const nums = useMemo(() => numbering(assets), [assets]);
  const legacy = useMemo(() => sections.flatMap((s, i) => s.slots.map((slot, k) => ({ slot, key: `${i}-${k}`, section: s.title }))), [sections]);
  const dirty =
    name !== format.title ||
    desc !== format.desc ||
    style !== (format.style ?? "") ||
    scope !== format.scope ||
    JSON.stringify(sections) !== JSON.stringify(format.sections) ||
    JSON.stringify(assets) !== JSON.stringify(format.assets ?? []);
  const sel = assets.find((a) => a.id === selId) ?? null;
  const pdf = /\.pdf$/i.test(format.sample || "") || format.kind === "format";
  const sectionTitle = (sid: string | null) => sections.find((s) => s.id === sid)?.title;

  const setSec = (i: number, patch: Partial<FormatSection>) => setSections((cur) => cur.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= sections.length) return;
    setSections((cur) => {
      const next = [...cur];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };
  const removeSec = (i: number) => setSections((cur) => cur.filter((_, j) => j !== i));
  const addSec = (at: number) => setSections((cur) => [...cur.slice(0, at), { title: "새 섹션", level: cur[at - 1]?.level ?? 1, guide: "", slots: [] }, ...cur.slice(at)]);
  const removeSlot = (i: number, k: number) => setSec(i, { slots: sections[i].slots.filter((_, j) => j !== k) });
  const setAsset = (id: string, patch: Partial<FormatAsset>) => setAssets((cur) => cur.map((a) => (a.id === id ? { ...a, ...patch } : a)));
  const removeAsset = (id: string) => {
    setAssets((cur) => cur.filter((a) => a.id !== id));
    if (selId === id) setSelId(assets.find((a) => a.id !== id)?.id ?? null);
  };
  const showAsset = (id: string) => {
    setSelId(id);
    setTab("assets");
  };

  /** 서버에서 온 양식으로 화면 상태를 맞춘다(저장·말로 고치기·등록 뒤) */
  const adopt = (f: DocFormat) => {
    onSaved(f);
    setName(f.title);
    setDesc(f.desc);
    setStyle(f.style ?? "");
    setSections(f.sections);
    setAssets(f.assets ?? []);
  };

  /** 직접 고친 것 저장 — 실패하면 null(알림은 여기서) */
  const persist = async (): Promise<DocFormat | null> => {
    if (sections.some((s) => !s.title.trim()) || assets.some((a) => !a.name.trim())) {
      toast.error("섹션·표·차트 이름을 적어 주세요.", { position: "top-center" });
      return null;
    }
    try {
      const f = await patchFormat(ws.workspaceId, format.id, {
        name: name.trim() || format.title,
        desc,
        style,
        sections,
        ...(format.assets?.length ? { assets: assets.map((a) => ({ id: a.id, name: a.name.trim(), desc: a.desc, ...(a.chart ? { chartType: a.chart.type } : {}) })) } : {}),
        ...(scope !== format.scope && scope !== "builtin" && !format.draft ? { scope: scope as TemplateScope } : {}),
      });
      adopt(f);
      return f;
    } catch (e) {
      toast.error(errText(e, "저장하지 못했습니다."), { position: "top-center" });
      return null;
    }
  };

  const save = async () => {
    setBusy(true);
    if (await persist()) toast.success("양식을 저장했습니다.", { position: "top-center" });
    setBusy(false);
  };

  /** 등록 전 양식 → 등록(고친 것이 있으면 먼저 저장) */
  const register = async () => {
    setBusy(true);
    try {
      if (dirty && !(await persist())) return;
      const f = await registerFormat(ws.workspaceId, format.id, (scope === "company" ? "company" : "workspace") as TemplateScope);
      adopt(f);
      toast.success(`문서 양식 '${f.title}' 을 등록했습니다.`, { position: "top-center" });
    } catch (e) {
      toast.error(errText(e, "등록하지 못했습니다."), { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    if (!window.confirm(`등록 전 양식 '${format.title}' 을 버릴까요?`)) return;
    setBusy(true);
    try {
      await deleteReportType(format.id);
      onRemoved();
    } catch (e) {
      toast.error(errText(e, "버리지 못했습니다."), { position: "top-center" });
      setBusy(false);
    }
  };

  /** 말로 고치기 — 직접 고친 것이 있으면 먼저 저장하고 AI 에게 */
  const revise = async () => {
    const text = ask.trim();
    if (!text) return;
    setRevising(true);
    setNote("");
    try {
      if (dirty && !(await persist())) return;
      const { format: f, summary } = await reviseFormat(ws.workspaceId, format.id, text);
      adopt(f);
      setAsk("");
      setNote(summary || "고쳤습니다.");
    } catch (e) {
      toast.error(errText(e, "AI 가 양식을 고치지 못했습니다."), { position: "top-center" });
    } finally {
      setRevising(false);
    }
  };

  const assetCount = assets.length || legacy.length;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-neutral-200 bg-white px-5 py-3">
        <button type="button" aria-label="양식 목록" onClick={onBack} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
          <ArrowLeft className="size-5" aria-hidden />
        </button>
        <input value={name} disabled={ro} onChange={(e) => setName(e.target.value)} aria-label="양식 이름" className={cn(field, "h-9 min-w-0 flex-1 text-[17px] font-bold text-text-primary")} />
        {format.draft && <span className="shrink-0 rounded-full bg-amber-50 px-2.5 py-1 text-[12px] font-semibold text-amber-700">등록 전</span>}
        {ro ? (
          <span className="shrink-0 rounded-full bg-neutral-100 px-2.5 py-1 text-[12px] font-medium text-neutral-600">{SCOPE_LABEL[format.scope]}</span>
        ) : (
          <select value={scope === "user" ? "workspace" : scope} onChange={(e) => setScope(e.target.value as DocFormat["scope"])} aria-label="범위" className="h-9 shrink-0 cursor-pointer rounded-lg bg-neutral-100 px-2 text-[13px] font-medium text-neutral-700 outline-none">
            <option value="workspace">워크스페이스</option>
            {(ws.role === "owner" || scope === "company") && <option value="company">사내</option>}
          </select>
        )}
        {ws.can("editor") && !format.draft && (
          <button type="button" disabled={starter.busy || dirty} title={dirty ? "고친 내용을 먼저 저장하세요" : "이 양식으로 새 AI 작업(문서 작성)"} onClick={() => void starter.start(format.id)} className="flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-3.5 text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40">
            {starter.busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <PenLine className="size-4" aria-hidden />}이 양식으로 쓰기
          </button>
        )}
        {format.draft && (
          <button type="button" disabled={busy || revising} onClick={() => void discard()} className="h-9 shrink-0 cursor-pointer rounded-xl bg-neutral-100 px-3.5 text-[13px] font-semibold text-neutral-700 hover:bg-red-50 hover:text-red-600 disabled:opacity-40">
            버리기
          </button>
        )}
        {!ro && (
          <button type="button" disabled={busy || revising || !dirty} onClick={() => void save()} className={cn("flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-xl px-4 text-[13px] font-semibold disabled:opacity-30", format.draft ? "bg-neutral-100 text-neutral-700 hover:bg-neutral-200" : "bg-neutral-900 text-white hover:bg-neutral-700")}>
            {busy && !format.draft && <Loader2 className="size-4 animate-spin" aria-hidden />}
            저장
          </button>
        )}
        {format.draft && (
          <button type="button" disabled={busy || revising} onClick={() => void register()} title="등록하면 다른 사람·새 문서에 보입니다" className="flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40">
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
            등록
          </button>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-neutral-100">
          <div className="flex h-11 shrink-0 items-center gap-1 border-b border-neutral-200 bg-white px-4">
            {(["doc", "assets"] as const).map((t) => (
              <button key={t} type="button" onClick={() => setTab(t)} className={cn("h-7 cursor-pointer rounded-md px-3 text-[13px] font-medium", tab === t ? "bg-primary-soft text-primary" : "text-text-secondary hover:bg-neutral-100")}>
                {t === "doc" ? "예시 문서" : `에셋${assetCount ? ` ${assetCount}` : ""}`}
              </button>
            ))}
          </div>

          <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {tab === "doc" ? (
              <div className="mx-auto flex max-w-[720px] flex-col gap-2">
                {(desc || !ro) && <input value={desc} disabled={ro} onChange={(e) => setDesc(e.target.value)} placeholder="설명(선택)" aria-label="양식 설명" className={cn(field, "h-9 w-full bg-white text-text-secondary")} />}
                {(style || !ro) && (
                  <div className="rounded-2xl bg-white p-3.5">
                    <p className="text-[12px] font-semibold text-neutral-500">문체·형식</p>
                    {ro ? (
                      <p className="mt-1.5 text-[13px] leading-6 whitespace-pre-wrap text-text-primary">{style}</p>
                    ) : (
                      <textarea value={style} onChange={(e) => setStyle(e.target.value)} rows={3} placeholder="문장 끝맺음, 문단 길이, 숫자·단위 표기, 소제목 꼴 — AI 가 쓸 때 따른다" aria-label="문체·형식" className={cn(field, "mt-1.5 w-full resize-y py-2 leading-5")} />
                    )}
                  </div>
                )}
                {sections.map((s, i) => {
                  const here = assets.filter((a) => a.sectionId && a.sectionId === s.id);
                  return (
                    <div key={s.id ?? `new${i}`} className={cn("rounded-2xl bg-white p-3.5", s.level === 2 && "ml-5", s.level === 3 && "ml-10")}>
                      <div className="flex items-center gap-2">
                        {!ro && (
                          <select value={s.level} onChange={(e) => setSec(i, { level: Number(e.target.value) })} aria-label="섹션 수준" className="h-8 shrink-0 cursor-pointer rounded-lg bg-neutral-100 px-1.5 text-[12px] text-neutral-600 outline-none">
                            {LEVELS.map((l) => (
                              <option key={l.v} value={l.v}>
                                {l.label}
                              </option>
                            ))}
                          </select>
                        )}
                        <input value={s.title} disabled={ro} onChange={(e) => setSec(i, { title: e.target.value })} aria-label="섹션 이름" className={cn(field, "h-8 min-w-0 flex-1 font-semibold text-text-primary", s.level === 1 && "text-[15px]")} />
                        {!ro && (
                          <span className="flex shrink-0 items-center">
                            <button type="button" aria-label="위로" disabled={i === 0} onClick={() => move(i, -1)} className="cursor-pointer rounded-md p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700 disabled:opacity-30">
                              <ArrowUp className="size-4" aria-hidden />
                            </button>
                            <button type="button" aria-label="아래로" disabled={i === sections.length - 1} onClick={() => move(i, 1)} className="cursor-pointer rounded-md p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700 disabled:opacity-30">
                              <ArrowDown className="size-4" aria-hidden />
                            </button>
                            <button type="button" aria-label="섹션 빼기" disabled={sections.length <= 1} onClick={() => removeSec(i)} className="cursor-pointer rounded-md p-1 text-neutral-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-30">
                              <Trash2 className="size-4" aria-hidden />
                            </button>
                          </span>
                        )}
                      </div>
                      {ro ? (
                        s.guide && <p className="mt-1.5 text-[13px] leading-5 text-text-secondary">{s.guide}</p>
                      ) : (
                        <textarea value={s.guide} onChange={(e) => setSec(i, { guide: e.target.value })} rows={2} placeholder="이 섹션의 꼴(다루는 항목·순서·문단 수)" aria-label="작성 안내" className={cn(field, "mt-2 w-full resize-y py-2 leading-5")} />
                      )}
                      {here.length > 0 && (
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          <span className="text-[11px] text-neutral-400">샘플에서 쓴 것</span>
                          {here.map((a) => {
                            const Icon = a.kind === "chart" ? BarChart3 : Table2;
                            return (
                              <button key={a.id} type="button" onClick={() => showAsset(a.id)} className="flex cursor-pointer items-center gap-1 rounded-full bg-neutral-100 py-1 pr-2.5 pl-2 text-[12px] text-neutral-700 hover:bg-primary-soft hover:text-primary">
                                <Icon className="size-3.5" aria-hidden />
                                <span className="max-w-[220px] truncate">{a.name}</span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                      {s.slots.length > 0 && (
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          {s.slots.map((x, k) => {
                            const Icon = slotIcon(x);
                            const key = `${i}-${k}`;
                            const on = openSlot === key;
                            return (
                              <span key={k} className={cn("flex items-center rounded-full text-[12px]", on ? "bg-primary text-white" : "bg-primary-soft text-primary")}>
                                <button type="button" onClick={() => setOpenSlot(on ? null : key)} className="flex cursor-pointer items-center gap-1 py-1 pr-1 pl-2.5">
                                  <Icon className="size-3.5" aria-hidden />
                                  <span className="max-w-[220px] truncate">{x.title}</span>
                                </button>
                                {!ro && (
                                  <button type="button" aria-label="자리 빼기" onClick={() => (removeSlot(i, k), setOpenSlot(null))} className="mr-1 cursor-pointer rounded-full p-0.5 opacity-70 hover:opacity-100">
                                    <X className="size-3" aria-hidden />
                                  </button>
                                )}
                              </span>
                            );
                          })}
                        </div>
                      )}
                      {openSlot?.startsWith(`${i}-`) && s.slots[Number(openSlot.split("-")[1])] && (
                        <div className="mt-2">
                          <SlotPreview slot={s.slots[Number(openSlot.split("-")[1])]} template={byId.get(s.slots[Number(openSlot.split("-")[1])].templateId ?? "")} />
                        </div>
                      )}
                      {!ro && (
                        <button type="button" onClick={() => addSec(i + 1)} className="mt-2 flex cursor-pointer items-center gap-1 text-[12px] text-neutral-400 hover:text-primary">
                          <Plus className="size-3.5" aria-hidden />
                          아래에 섹션
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="mx-auto flex max-w-[760px] flex-col gap-3">
                {assets.length === 0 && legacy.length === 0 && <p className="py-10 text-center text-[13px] text-text-secondary">이 양식에는 표·차트 양식이 없습니다.</p>}
                {assets.map((a) => {
                  const on = a.id === selId;
                  const Icon = a.kind === "chart" ? BarChart3 : Table2;
                  const where = sectionTitle(a.sectionId);
                  return (
                    <div
                      key={a.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => setSelId(a.id)}
                      onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && setSelId(a.id)}
                      className={cn("cursor-pointer rounded-2xl bg-white p-4 transition-shadow", on ? "ring-2 ring-primary" : "ring-1 ring-neutral-200 hover:ring-neutral-300")}
                    >
                      <div className="flex items-center gap-2">
                        <Icon className="size-4 shrink-0 text-primary" aria-hidden />
                        <input value={a.name} disabled={ro} onClick={(e) => e.stopPropagation()} onChange={(e) => setAsset(a.id, { name: e.target.value })} aria-label="표·차트 양식 이름" className={cn(field, "h-8 min-w-0 flex-1 font-semibold text-text-primary")} />
                        {!ro && a.chart ? (
                          <select value={a.chart.type} onClick={(e) => e.stopPropagation()} onChange={(e) => setAsset(a.id, { chart: { ...a.chart!, type: e.target.value as NonNullable<FormatAsset["chart"]>["type"] } })} aria-label="차트 종류" className="h-7 shrink-0 cursor-pointer rounded-lg bg-neutral-100 px-1.5 text-[12px] text-neutral-700 outline-none">
                            {Object.entries(CHART_LABEL).map(([v, l]) => (
                              <option key={v} value={v}>
                                {v === "other" ? "그 밖 차트" : `${l} 차트`}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="shrink-0 rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] text-neutral-600">{a.kind === "chart" ? `${CHART_LABEL[a.chart?.type ?? "other"]} 차트` : "표"}</span>
                        )}
                        {a.position === "sidebar" && <span className="shrink-0 text-[11px] text-neutral-500">옆 칸</span>}
                        {!ro && (
                          <button type="button" aria-label="표·차트 양식 빼기" onClick={(e) => (e.stopPropagation(), removeAsset(a.id))} className="shrink-0 cursor-pointer rounded-md p-1 text-neutral-400 hover:bg-red-50 hover:text-red-600">
                            <Trash2 className="size-4" aria-hidden />
                          </button>
                        )}
                      </div>
                      {ro ? (
                        a.desc && <p className="mt-1 text-[12.5px] leading-5 text-text-secondary">{a.desc}</p>
                      ) : (
                        <input value={a.desc} onClick={(e) => e.stopPropagation()} onChange={(e) => setAsset(a.id, { desc: e.target.value })} placeholder="구성 한 줄" aria-label="구성 설명" className={cn(field, "mt-1.5 h-8 w-full text-text-secondary")} />
                      )}
                      {where && <p className="mt-1 text-[11px] text-neutral-400">샘플: {where}</p>}
                      <div className="mt-3 rounded-xl border border-neutral-100 p-3">
                        <AssetFormView asset={a} n={nums.get(a.id) ?? 1} />
                      </div>
                    </div>
                  );
                })}
                {assets.length === 0 &&
                  legacy.map(({ slot, key, section }) => (
                    <div key={key}>
                      <p className="mb-1 px-1 text-[11px] text-neutral-400">{section}</p>
                      <SlotPreview slot={slot} template={byId.get(slot.templateId ?? "")} />
                    </div>
                  ))}
              </div>
            )}
          </div>
          {!ro && (
            <div className="shrink-0 border-t border-neutral-200 bg-white px-4 py-3">
              {note && (
                <p className="mb-2 flex items-start gap-1.5 text-[12.5px] text-text-secondary">
                  <Sparkles className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
                  {note}
                </p>
              )}
              <div className="flex items-end gap-2">
                <textarea
                  value={ask}
                  disabled={revising}
                  onChange={(e) => setAsk(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      void revise();
                    }
                  }}
                  rows={1}
                  placeholder="AI 에게 고쳐 달라고 하기 — 예: 2번 섹션 안내를 표 위주로 바꿔줘 / 'ETF 수익률 표' 는 빼줘"
                  aria-label="AI 에게 고쳐 달라고 하기"
                  className="max-h-28 min-h-10 flex-1 resize-none rounded-xl bg-neutral-100 px-3.5 py-2.5 text-[13px] leading-5 outline-none focus:bg-white focus:ring-2 focus:ring-primary/30 disabled:opacity-60"
                />
                <button type="button" aria-label="고쳐 달라고 보내기" disabled={revising || !ask.trim()} onClick={() => void revise()} className="flex size-10 shrink-0 cursor-pointer items-center justify-center rounded-xl bg-primary text-white hover:bg-primary-hover disabled:opacity-40">
                  {revising ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
                </button>
              </div>
            </div>
          )}
        </div>

        <aside className="flex w-[460px] shrink-0 flex-col border-l border-neutral-200 bg-[#fbfcfd]">
          <div className="flex h-11 shrink-0 items-center gap-2 border-b border-neutral-200 px-4">
            <span className="text-[13px] font-semibold text-text-primary">원본</span>
            {tab === "assets" && sel?.source.page ? <span className="min-w-0 truncate text-[12px] text-text-secondary">p.{sel.source.page}{sel.source.caption ? ` · ${sel.source.caption}` : ""}</span> : null}
            {format.hasSample && (
              <a href={formatSampleUrl(ws.workspaceId, format.id) + (tab === "assets" && sel?.source.page && pdf ? `#page=${sel.source.page}` : "")} target="_blank" rel="noreferrer" className="ml-auto flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-[12px] text-text-secondary hover:bg-neutral-100">
                <ExternalLink className="size-3.5" aria-hidden />
                {tab === "assets" && sel?.source.page ? "쪽 전체" : "새 창"}
              </a>
            )}
          </div>
          {!format.hasSample ? (
            <p className="px-5 py-6 text-[13px] text-text-secondary">이 양식에는 원본(예시 문서)이 없습니다.</p>
          ) : tab === "assets" && sel ? (
            sel.source.box && pdf ? (
              <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto p-4">
                {/* eslint-disable-next-line @next/next/no-img-element -- 서버가 잘라 낸 PNG(로그인 uid 쿼리) */}
                <img key={sel.id} src={formatAssetImageUrl(ws.workspaceId, format.id, sel.id)} alt={`원본 ${sel.source.caption || sel.name}`} className="w-full rounded-lg bg-white ring-1 ring-neutral-200" />
              </div>
            ) : pdf && sel.source.page ? (
              <iframe key={sel.id} title="원본" src={`${formatSampleUrl(ws.workspaceId, format.id)}#page=${sel.source.page}`} className="min-h-0 w-full flex-1 bg-white" />
            ) : (
              <p className="px-5 py-6 text-[13px] text-text-secondary">이 표·차트는 원본 위치가 없습니다(Word 샘플). 위 '새 창'으로 원본을 엽니다.</p>
            )
          ) : tab === "assets" && assets.length > 0 ? (
            <p className="px-5 py-6 text-[13px] text-text-secondary">표·차트를 고르면 원본에서 그 부분을 보입니다.</p>
          ) : pdf ? (
            <iframe title="원본" src={formatSampleUrl(ws.workspaceId, format.id)} className="min-h-0 w-full flex-1 bg-white" />
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
              <FileText className="size-8 text-neutral-400" aria-hidden />
              <p className="text-[13px] text-text-secondary">{format.sample}</p>
              <a href={formatSampleUrl(ws.workspaceId, format.id)} target="_blank" rel="noreferrer" className="rounded-xl bg-neutral-100 px-3.5 py-2 text-[13px] font-semibold text-neutral-700 hover:bg-neutral-200">
                원본 열기
              </a>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
