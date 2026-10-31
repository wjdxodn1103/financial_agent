"use client";

/**
 * 검색·자료 가공 탭 — [찾기] 문서·문단·숫자·자료 속 표·시계열·정리한 데이터(종류·발행처·기간 거르기) → 담기 → [표로]·[차트로](칸마다 원문)
 * → 결과 서랍에서 드라이브에 저장·보내기·AI 작업에서 열기(이 자료로 문서 쓰기). [묻기] 는 자연어 질의 → 표 계획 → 원장에서 칸마다 원문으로 채운 표.
 */
import { useEffect, useRef, useState } from "react";
import { BarChart3, Check, FileText, Hash, Loader2, Search, Sparkles, Table2, TrendingUp, X } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ApiError, jsonInit, req } from "../report/api";
import { useWorkspace } from "../workspace/context";
import { AssetDrawer } from "../workspace/components/views/AssetsView";
import { useOpenSource } from "../workspace/sourceHost";
import { SeriesModal } from "../dashboards/widgets";
import { LineChart } from "../dashboards/charts";
import type { SeriesView } from "../data/types";

type Item = { kind: string; title: string; text?: string; sub?: string; id?: string; docId?: string | null; chunk?: string | null; cell?: [number, number] | null; key?: string; reportId?: string };
type Group = { kind: string; label: string; items: Item[] };

const KIND_CHIPS: { id: string; label: string }[] = [
  { id: "", label: "전체" },
  { id: "file", label: "문서" },
  { id: "document", label: "문단" },
  { id: "figure", label: "숫자" },
  { id: "table", label: "자료 속 표" },
  { id: "series", label: "시계열" },
  { id: "asset", label: "정리한 데이터" },
];
const DOC_TYPES = ["", "공시", "뉴스·보도자료", "분기·반기보고서", "사업보고서", "IR 자료", "애널리스트 리포트", "경제·산업 자료", "내부 규정·지침"];
const PICKABLE = new Set(["figure", "table", "document"]);
const ICON: Record<string, typeof FileText> = { figure: Hash, table: Table2, series: TrendingUp, document: FileText, file: FileText };

const wid = (w: string) => `/api/workspaces/${encodeURIComponent(w)}`;
const keyOf = (it: Item) => `${it.kind}:${it.key ?? it.id ?? ""}:${it.docId ?? ""}:${it.chunk ?? ""}`;

export function SearchStudio({ query }: { query: string }) {
  const ws = useWorkspace();
  const openSource = useOpenSource();
  const [mode, setMode] = useState<"find" | "ask">("find");
  const [q, setQ] = useState(query);
  const [kind, setKind] = useState("");
  const [docType, setDocType] = useState("");
  const [issuer, setIssuer] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [basket, setBasket] = useState<Item[]>([]);
  const [drawer, setDrawer] = useState<string | null>(null);
  const [series, setSeries] = useState<string | null>(null);
  const [ask, setAsk] = useState<{ plan: Record<string, unknown>; summary: string; tableId: string | null; series: SeriesView[] } | null>(null);
  const seq = useRef(0);

  const find = async () => {
    const n = ++seq.current;
    setBusy(true);
    try {
      const p = new URLSearchParams({ q, kinds: kind, docType, issuer, since, until });
      const r = await req<{ groups: Group[] }>(`${wid(ws.workspaceId)}/search/studio?${p.toString()}`);
      if (n === seq.current) setGroups(r.groups);
    } catch {
      if (n === seq.current) setGroups([]);
    } finally {
      if (n === seq.current) setBusy(false);
    }
  };
  useEffect(() => {
    if (mode === "find" && q.trim()) void find();
  }, [kind, docType]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setQ(query);
    if (query.trim()) {
      setMode("find");
      window.setTimeout(() => void find(), 0);
    }
  }, [query]); // eslint-disable-line react-hooks/exhaustive-deps

  const askNow = async () => {
    if (!q.trim()) return;
    setBusy(true);
    setAsk(null);
    try {
      const r = await req<{ plan: Record<string, unknown>; summary: string; tableId: string | null; series: SeriesView[] }>(`${wid(ws.workspaceId)}/search/query`, jsonInit("POST", { q }));
      setAsk(r);
      if (r.tableId) setDrawer(r.tableId);
      if (!r.tableId && !r.series.length) toast.error("표로 만들 만한 행·열을 찾지 못했습니다. 기업·지표·기간을 넣어 다시 물어 주세요.", { position: "top-center" });
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "질의를 처리하지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  const toggle = (it: Item) => setBasket((b) => (b.some((x) => keyOf(x) === keyOf(it)) ? b.filter((x) => keyOf(x) !== keyOf(it)) : [...b, it]));
  const compose = async (op: "table" | "chart") => {
    setBusy(true);
    try {
      const r = await req<{ tables: string[]; charts: string[]; open: string }>(`${wid(ws.workspaceId)}/search/compose`, jsonInit("POST", { items: basket, op, title: q.trim().slice(0, 40) }));
      setDrawer(r.open);
      setBasket([]);
      toast.success(`${op === "chart" ? "차트" : "표"}를 만들었습니다 — 저장하면 드라이브 '정리한 데이터'에 남습니다.`, { position: "top-center" });
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "만들지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  const open = (it: Item) => {
    if (it.kind === "series" && it.id) return setSeries(it.id);
    if (it.kind === "asset" && it.id) return setDrawer(it.id);
    if (it.kind === "doc" && (it.id || it.reportId)) return ws.nav.openReport((it.id ?? it.reportId)!);
    if (it.kind === "folder" && it.id) return ws.nav.openFolder(it.id);
    if (it.docId) openSource(it.docId, it.chunk ?? null, it.cell ?? null);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "ask") void askNow();
    else void find();
  };

  const chip = (on: boolean) => cn("cursor-pointer rounded-lg px-2.5 py-1 text-[12px] font-medium", on ? "bg-primary-soft text-primary" : "bg-white text-neutral-700 hover:bg-neutral-50");

  return (
    <div className="relative flex min-h-0 flex-1 flex-col bg-neutral-100">
      <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1080px] px-8 pt-8 pb-32">
          <h1 className="text-[26px] font-bold tracking-tight text-text-primary">검색</h1>
          <form onSubmit={submit} className="mt-4 flex items-center gap-2 rounded-2xl bg-white px-4 py-2 shadow-[0_2px_12px_rgba(0,27,55,0.06)]">
            <div className="flex shrink-0 rounded-lg bg-neutral-100 p-0.5 text-[12px] font-semibold">
              <button type="button" onClick={() => setMode("find")} className={cn("cursor-pointer rounded-md px-2.5 py-1", mode === "find" ? "bg-white text-text-primary shadow-sm" : "text-text-secondary")}>
                찾기
              </button>
              <button type="button" onClick={() => setMode("ask")} className={cn("cursor-pointer rounded-md px-2.5 py-1", mode === "ask" ? "bg-white text-primary shadow-sm" : "text-text-secondary")}>
                묻기
              </button>
            </div>
            {mode === "ask" ? <Sparkles className="size-4 shrink-0 text-primary" aria-hidden /> : <Search className="size-4 shrink-0 text-neutral-500" aria-hidden />}
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={mode === "ask" ? "예: 가온전자·나래바이오 2022~2024 영업이익률" : "자료·숫자·표·시계열 찾기"}
              className="h-10 min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-neutral-400"
            />
            <button type="submit" disabled={busy || !q.trim()} className="flex h-9 shrink-0 cursor-pointer items-center gap-1 rounded-xl bg-primary px-4 text-[13px] font-semibold text-white disabled:opacity-40">
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : mode === "ask" ? "표 만들기" : "찾기"}
            </button>
          </form>

          {mode === "find" && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {KIND_CHIPS.map((k) => (
                <button key={k.id} type="button" onClick={() => setKind(k.id)} className={chip(kind === k.id)}>
                  {k.label}
                </button>
              ))}
              <span className="mx-1 h-4 w-px bg-neutral-300" />
              <select value={docType} onChange={(e) => setDocType(e.target.value)} aria-label="문서 종류" className="h-7 rounded-lg bg-white px-2 text-[12px]">
                {DOC_TYPES.map((d) => (
                  <option key={d} value={d}>
                    {d || "문서 종류 전체"}
                  </option>
                ))}
              </select>
              <input value={issuer} onChange={(e) => setIssuer(e.target.value)} onBlur={() => q.trim() && void find()} placeholder="발행처" className="h-7 w-28 rounded-lg bg-white px-2 text-[12px] outline-none" />
              <input type="date" value={since} onChange={(e) => setSince(e.target.value)} onBlur={() => q.trim() && void find()} aria-label="부터" className="h-7 rounded-lg bg-white px-2 text-[12px]" />
              <span className="text-[12px] text-text-secondary">~</span>
              <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} onBlur={() => q.trim() && void find()} aria-label="까지" className="h-7 rounded-lg bg-white px-2 text-[12px]" />
            </div>
          )}

          {mode === "ask" && ask && (
            <section className="mt-4 rounded-[20px] bg-white px-5 py-4">
              <p className="text-[13px] font-semibold text-text-secondary">처리 단계</p>
              <ol className="mt-1.5 flex flex-col gap-1 text-[13px] text-text-primary">
                <li>1. 질문 → 표 계획: 행 {((ask.plan.rows as string[]) ?? []).join(", ") || "—"} · 열 {((ask.plan.columns as { label: string }[]) ?? []).map((c) => c.label).join(", ") || "—"}
                  {ask.plan.period ? ` · 기준 ${String(ask.plan.period)}` : ""}</li>
                <li>2. 값은 원장(사내 데이터의 표 칸)에서 코드로 — 칸마다 원문 연결, 못 찾은 칸은 빈 칸</li>
                {ask.summary && <li className="whitespace-pre-wrap text-text-secondary">3. {ask.summary.split("\n")[0]}</li>}
              </ol>
              {ask.tableId && (
                <button type="button" onClick={() => setDrawer(ask.tableId)} className="mt-2 text-[13px] font-semibold text-primary hover:underline">
                  만든 표 열기
                </button>
              )}
              {ask.series.length > 0 && (
                <div className="mt-3">
                  <LineChart series={ask.series.map((s) => ({ name: s.name + (s.virtual ? "(가상)" : ""), points: s.points, decimals: s.decimals, unit: s.unit }))} />
                </div>
              )}
            </section>
          )}

          {mode === "find" && groups && groups.length === 0 && !busy && <p className="mt-10 text-center text-[14px] text-text-secondary">찾은 것이 없습니다.</p>}
          {mode === "find" &&
            groups?.map((g) => (
              <section key={g.kind} className="mt-5">
                <h2 className="mb-2 px-1 text-[13px] font-semibold text-text-secondary">
                  {g.label} <span className="text-neutral-400">{g.items.length}</span>
                </h2>
                <div className="overflow-hidden rounded-[20px] bg-white">
                  {g.items.map((it, i) => {
                    const on = basket.some((x) => keyOf(x) === keyOf(it));
                    const Icon = ICON[it.kind] ?? FileText;
                    return (
                      <div key={`${keyOf(it)}${i}`} className="flex items-start gap-3 border-b border-neutral-100 px-4 py-2.5 last:border-0 hover:bg-neutral-50">
                        {PICKABLE.has(it.kind) ? (
                          <button type="button" aria-label={on ? "빼기" : "담기"} onClick={() => toggle(it)} className={cn("mt-0.5 flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-md border", on ? "border-primary bg-primary text-white" : "border-neutral-300 bg-white")}>
                            {on && <Check className="size-3.5" aria-hidden />}
                          </button>
                        ) : (
                          <Icon className="mt-0.5 size-5 shrink-0 text-neutral-400" aria-hidden />
                        )}
                        <button type="button" onClick={() => open(it)} className="min-w-0 flex-1 cursor-pointer text-left">
                          <span className="block truncate text-[14px] font-medium text-text-primary">{it.title}</span>
                          {it.text && <span className="mt-0.5 line-clamp-2 block text-[12px] text-text-secondary">{it.text}</span>}
                          {it.sub && <span className="mt-0.5 block truncate text-[11px] text-neutral-400">{it.sub}</span>}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
        </div>
      </div>

      {basket.length > 0 && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center px-8 pb-5">
          <div className="pointer-events-auto flex w-full max-w-[640px] items-center gap-3 rounded-[20px] bg-white px-4 py-3 shadow-[0_8px_30px_rgba(0,27,55,0.14)]">
            <span className="text-[14px] font-semibold text-text-primary">{basket.length}개 담음</span>
            <span className="min-w-0 flex-1 truncate text-[12px] text-text-secondary">{basket.map((b) => b.title).join(" · ")}</span>
            <button type="button" onClick={() => setBasket([])} aria-label="비우기" className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
              <X className="size-4" aria-hidden />
            </button>
            <button type="button" disabled={busy} onClick={() => void compose("table")} className="flex h-9 cursor-pointer items-center gap-1 rounded-xl bg-neutral-100 px-3 text-[13px] font-semibold text-neutral-700 hover:bg-neutral-200 disabled:opacity-40">
              <Table2 className="size-4" aria-hidden />
              표로
            </button>
            <button type="button" disabled={busy} onClick={() => void compose("chart")} className="flex h-9 cursor-pointer items-center gap-1 rounded-xl bg-primary px-3 text-[13px] font-semibold text-white disabled:opacity-40">
              <BarChart3 className="size-4" aria-hidden />
              차트로
            </button>
          </div>
        </div>
      )}
      {drawer && <AssetDrawer key={drawer} id={drawer} taskId={null} onClose={() => setDrawer(null)} onChanged={() => undefined} onRemoved={() => setDrawer(null)} className="fixed inset-y-0 right-0 z-40 shadow-2xl" />}
      {series && <SeriesModal id={series} onClose={() => setSeries(null)} />}
    </div>
  );
}
