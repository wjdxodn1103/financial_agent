"use client";

/** 대시보드 위젯 — 값은 서버가 계산(관측값·원장·기록), 화면은 그리기만. 변화는 숫자와 ▲▼ 기호로만(판정 색 없음). */
import { useEffect, useState } from "react";
import { useSetAtom } from "jotai";
import { AlertCircle, FileText, ListChecks, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { getMarketSeries } from "../data/api";
import type { DataIssueView, SeriesCard, SeriesView } from "../data/types";
import { assumptionsDrawerAtom } from "../assumptions/state";
import { useWorkspace } from "../workspace/context";
import { useOpenSource } from "../workspace/sourceHost";
import { Thumbs } from "../workspace/components/Thumbs";
import { getBrief, getMarketHomeChart } from "./api";
import { LineChart, Sparkline } from "./charts";
import { PeerBoard } from "./peer/PeerBoard";
import type { BriefFact, BriefView, IngestStats, Widget, WidgetSize } from "./types";

export const SIZE_CLASS: Record<WidgetSize, string> = { s: "lg:col-span-3", m: "lg:col-span-4", l: "lg:col-span-6", full: "lg:col-span-12" };

const arrow = (v: number) => (v > 0 ? "▲" : v < 0 ? "▼" : "");
const ko: Record<string, string> = { d1: "전일", w1: "1주", m1: "1달" };

function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function SeriesCardView({ c, onOpen }: { c: SeriesCard; onOpen: (id: string) => void }) {
  return (
    <button type="button" onClick={() => onOpen(c.id)} className="flex min-w-0 cursor-pointer flex-col gap-1 rounded-2xl bg-neutral-50 px-4 py-3 text-left hover:bg-neutral-100">
      <span className="flex items-center gap-1.5">
        <span className="truncate text-[13px] font-semibold text-text-primary">{c.name}</span>
        {c.virtual && <span className="shrink-0 rounded bg-amber-50 px-1 text-[10px] font-medium text-amber-700">가상</span>}
      </span>
      <span className="flex items-end justify-between gap-2">
        <span className="num text-[20px] leading-tight font-bold text-text-primary">
          {c.display ?? "—"}
          <span className="ml-1 text-[12px] font-medium text-text-secondary">{c.unit}</span>
        </span>
        <Sparkline values={c.spark} width={84} height={28} className="shrink-0" />
      </span>
      <span className="num flex flex-wrap gap-x-2.5 text-[11px] text-neutral-600">
        {(["d1", "w1", "m1"] as const).map((k) =>
          c.changes[k] ? (
            <span key={k} title={`${c.changes[k]!.from.date} ${c.changes[k]!.from.display}`}>
              {ko[k]} {arrow(c.changes[k]!.value)}
              {c.changes[k]!.display.replace(/^[+-]/, "")}
            </span>
          ) : null,
        )}
      </span>
      <span className="truncate text-[10px] text-neutral-400">
        {c.date} · {c.sourceLabel}
        {c.fallback && " (대체)"}
        {c.status === "stale" && " · 기준일 지남"}
      </span>
    </button>
  );
}

/** 시리즈 차트 창 — id = 시장 시계열, ticker = 시장 홈 Yahoo 시세(지수·환율·원자재) */
export function SeriesModal({ id, ticker, onClose }: { id?: string; ticker?: string; onClose: () => void }) {
  const [range, setRange] = useState("1Y");
  const [v, setV] = useState<SeriesView | null>(null);
  useEffect(() => {
    let off = false;
    setV(null);
    const get = ticker
      ? getMarketHomeChart(ticker, range).then((c): SeriesView => ({ id: c.ticker, name: c.name, unit: c.unit, decimals: c.decimals, source: "yahoo", sourceLabel: c.source, virtual: false, range: c.range, points: c.points }))
      : getMarketSeries(id ?? "", range);
    void get.then((x) => !off && setV(x), () => undefined);
    return () => {
      off = true;
    };
  }, [id, ticker, range]);
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 px-4" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="w-full max-w-[760px] rounded-[24px] bg-white p-6 shadow-xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[18px] font-bold text-text-primary">
              {v?.name ?? "…"}
              {v?.virtual && <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">가상</span>}
            </p>
            <p className="text-[12px] text-text-secondary">
              {v ? `${v.unit} · 출처 ${v.sourceLabel} · 관측 ${v.points.length}개` : ""}
            </p>
          </div>
          <div className="flex items-center gap-1">
            {["1M", "3M", "6M", "1Y"].map((r) => (
              <button key={r} type="button" onClick={() => setRange(r)} className={cn("cursor-pointer rounded-lg px-2 py-1 text-[12px] font-semibold", r === range ? "bg-primary-soft text-primary" : "text-text-secondary hover:bg-neutral-100")}>
                {r}
              </button>
            ))}
            <button type="button" aria-label="닫기" onClick={onClose} className="ml-1 cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
              <X className="size-5" aria-hidden />
            </button>
          </div>
        </div>
        <div className="mt-4">{v ? <LineChart series={[{ name: v.name, points: v.points, decimals: v.decimals, unit: v.unit }]} height={260} /> : <Loader2 className="mx-auto my-16 size-5 animate-spin text-neutral-400" />}</div>
      </div>
    </div>
  );
}

/** [F#] 자리에 사실표 값 칩 — 누르면 그 시리즈 차트 */
function Sentence({ text, facts, onFact }: { text: string; facts: BriefFact[]; onFact: (f: BriefFact) => void }) {
  const parts = text.split(/(\[F\d+\])/g);
  return (
    <>
      {parts.map((p, i) => {
        const m = p.match(/^\[(F\d+)\]$/);
        const f = m ? facts.find((x) => x.id === m[1]) : null;
        if (!f) return <span key={i}>{p}</span>;
        return (
          <button key={i} type="button" onClick={() => onFact(f)} title={f.text} className="num mx-0.5 inline cursor-pointer rounded-md bg-primary-soft px-1.5 py-px text-[13px] font-semibold text-primary hover:underline">
            {f.value}
            {f.unit && f.unit !== "pt" ? ` ${f.unit}` : ""}
            {f.changes?.d1 && <span className="ml-1 font-medium text-primary/80">전일 {f.changes.d1}</span>}
            {f.virtual && <span className="ml-1 text-amber-700">가상</span>}
          </button>
        );
      })}
    </>
  );
}

function AiSummary({ initial, onSeries }: { initial: Partial<BriefView>; onSeries: (id: string) => void }) {
  const [b, setB] = useState<Partial<BriefView>>(initial);
  const [ticker, setTicker] = useState<string | null>(null);
  useEffect(() => setB(initial), [initial]);
  const pick = (d: string) => void getBrief(d).then(setB, () => undefined);
  const facts = b.facts ?? [];
  const onFact = (f: BriefFact) => (f.ticker ? setTicker(f.ticker) : f.seriesId && onSeries(f.seriesId));
  if (!b.summary?.length) return <p className="py-6 text-[13px] text-text-secondary">아직 오늘의 요약이 없습니다(시장 시계열 수집 뒤에 만들어집니다).</p>;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-[12px] text-text-secondary">
        <select value={b.date ?? ""} onChange={(e) => pick(e.target.value)} className="h-7 rounded-lg bg-neutral-100 px-2 text-[12px]">
          {(b.dates ?? []).map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <span>{when(b.createdAt)} 작성 · 숫자는 사실표(관측값)에서</span>
        <span className="flex-1" />
        {b.date && <Thumbs targetKind="brief" targetId={b.date} />}
      </div>
      <ul className="flex flex-col gap-1.5 text-[14px] leading-7 text-text-primary">
        {b.summary.map((s, i) => (
          <li key={i}>
            <Sentence text={s} facts={facts} onFact={onFact} />
          </li>
        ))}
      </ul>
      {!!b.judgement?.length && (
        <div className="rounded-2xl bg-neutral-50 px-4 py-3">
          <p className="mb-1 text-[12px] font-semibold text-text-secondary">AI 판단</p>
          {b.judgement.map((s, i) => (
            <p key={i} className="text-[13px] leading-6 text-text-primary">
              <Sentence text={s} facts={facts} onFact={onFact} />
            </p>
          ))}
        </div>
      )}
      {ticker && <SeriesModal ticker={ticker} onClose={() => setTicker(null)} />}
    </div>
  );
}

function ChangeTable({ rows, onOpen }: { rows: SeriesCard[]; onOpen: (id: string) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="num w-full text-[13px]">
        <thead>
          <tr className="text-[11px] text-text-secondary">
            <th className="py-1.5 text-left font-medium">항목</th>
            <th className="py-1.5 text-right font-medium">값</th>
            <th className="py-1.5 text-right font-medium">전일</th>
            <th className="py-1.5 text-right font-medium">1주</th>
            <th className="py-1.5 text-right font-medium">1달</th>
            <th className="py-1.5 text-right font-medium">기준일·출처</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id} onClick={() => onOpen(c.id)} className="cursor-pointer border-t border-neutral-100 hover:bg-neutral-50">
              <td className="py-1.5 font-medium text-text-primary">
                {c.name}
                {c.virtual && <span className="ml-1 text-[10px] text-amber-700">가상</span>}
              </td>
              <td className="py-1.5 text-right">
                {c.display ?? "—"} <span className="text-[11px] text-text-secondary">{c.unit}</span>
              </td>
              {(["d1", "w1", "m1"] as const).map((k) => (
                <td key={k} className="py-1.5 text-right text-neutral-700">
                  {c.changes[k] ? `${arrow(c.changes[k]!.value)}${c.changes[k]!.display.replace(/^[+-]/, "")}` : "—"}
                </td>
              ))}
              <td className="py-1.5 text-right text-[11px] text-text-secondary">
                {c.date} · {c.sourceLabel}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const ISSUE_TEXT = (i: DataIssueView): string => {
  const d = i.detail as Record<string, unknown>;
  switch (i.kind) {
    case "disagree": {
      const a = d.a as { provider: string; value: number };
      const b = d.b as { provider: string; value: number };
      return `${d.name} ${d.date}: ${a.provider} ${a.value} vs ${b.provider} ${b.value}`;
    }
    case "stale":
      return `${d.name} — 마지막 값 ${d.lastDate} (${d.provider})`;
    case "missing":
      return `${d.name} — ${d.from}~${d.to} 영업일 ${d.businessDays}일 빔`;
    case "outlier":
      return `${d.name} ${d.date}: ${d.prev} → ${d.value} (${d.sigma}σ)`;
    case "doc_mismatch":
      return `${d.metric} ${d.period}: ${((d.values as string[]) ?? []).join(" / ")}`;
    case "ingest_failed":
      return `${d.source} — ${d.title}: ${d.error ?? ""}`;
    default:
      return JSON.stringify(d).slice(0, 120);
  }
};

function SourceStatus({ w }: { w: Widget }) {
  const ws = useWorkspace();
  const srcs = w.data.sources ?? [];
  const series = (w.data.series ?? []) as { id: string; name: string; providerLabel: string; fallback: boolean; lastDate: string | null; providers: Record<string, { status: string }> }[];
  const fb = series.filter((s) => s.fallback);
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="flex flex-col">
        {srcs.map((s) => (
          <button key={s.id} type="button" onClick={() => ws.nav.view("sources")} className="flex cursor-pointer items-center gap-3 border-b border-neutral-100 py-2 text-left last:border-0 hover:bg-neutral-50">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-semibold text-text-primary">
                {s.name}
                {s.scope === "company" && <span className="ml-1.5 text-[11px] font-normal text-text-secondary">사내 공용</span>}
              </span>
              <span className="block truncate text-[11px] text-text-secondary">
                마지막 {when(s.lastRunAt) || "—"} · 다음 {when(s.nextRunAt) || "—"} · 항목 {s.items}
              </span>
            </span>
            <span className="shrink-0 text-[12px] text-neutral-700">
              {s.lastRun ? ({ ok: "정상", partial: "일부 실패", error: "실패", running: "수집 중" } as Record<string, string>)[s.lastRun.status] ?? s.lastRun.status : "—"}
              {s.failedItems > 0 && ` · 실패 ${s.failedItems}`}
            </span>
          </button>
        ))}
      </div>
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-1.5">
          {(w.data.providers ?? []).map((p) => (
            <span key={p.provider} className="rounded-lg bg-neutral-100 px-2 py-1 text-[11px] text-neutral-700">
              {p.label} · 정상 {p.ok}
              {p.error ? ` · 실패 ${p.error}` : ""}
              {p.nokey ? ` · 키 없음 ${p.nokey}` : ""}
            </span>
          ))}
        </div>
        <p className="text-[12px] font-semibold text-text-secondary">대체 소스로 받는 시리즈 {fb.length}</p>
        <div className="flex flex-col gap-0.5 text-[12px] text-neutral-700">
          {fb.slice(0, 10).map((s) => (
            <span key={s.id} className="truncate">
              {s.name} — {s.providerLabel}
              {Object.entries(s.providers).find(([, v]) => v.status === "nokey") ? " (FRED 키 없음)" : ""}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stats({ s }: { s: Partial<IngestStats> }) {
  const items: [string, number | undefined][] = [
    ["사내 공용 문서", s.companyDocs],
    ["워크스페이스 문서", s.workspaceDocs],
    ["문단(청크)", s.chunks],
    ["원장 수치", s.figures],
    ["시계열", s.series],
    ["관측값", s.observations],
    ["수집 항목", s.items],
    ["최근 7일 새 항목", s.itemsWeek],
  ];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {items.map(([k, v]) => (
        <div key={k} className="rounded-2xl bg-neutral-50 px-3 py-2.5">
          <p className="text-[11px] text-text-secondary">{k}</p>
          <p className="num text-[18px] font-bold text-text-primary">{(v ?? 0).toLocaleString("ko-KR")}</p>
        </div>
      ))}
    </div>
  );
}

export function WidgetBody({ w, onSeries }: { w: Widget; onSeries: (id: string) => void }) {
  const ws = useWorkspace();
  const openAssumption = useSetAtom(assumptionsDrawerAtom);
  const openSource = useOpenSource();
  const d = w.data;
  if (d.error) return <p className="text-[13px] text-text-secondary">이 위젯을 그리지 못했습니다.</p>;
  switch (w.type) {
    case "series_cards":
      return (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {(d.cards ?? []).map((c) => (
            <SeriesCardView key={c.id} c={c} onOpen={onSeries} />
          ))}
        </div>
      );
    case "change_table":
      return <ChangeTable rows={d.rows ?? []} onOpen={onSeries} />;
    case "series_chart": {
      const series = (d.series ?? []) as SeriesView[];
      return <LineChart series={series.map((s) => ({ name: s.name + (s.virtual ? "(가상)" : ""), points: s.points, decimals: s.decimals, unit: s.unit }))} />;
    }
    case "ai_summary":
      return <AiSummary initial={d} onSeries={onSeries} />;
    case "source_status":
      return <SourceStatus w={w} />;
    case "ingest_stats":
      return <Stats s={d} />;
    case "data_issues":
      return (d.issues ?? []).length ? (
        <div className="flex flex-col">
          {(d.issues ?? []).map((i) => (
            <div key={i.id} className="flex items-start gap-2 border-b border-neutral-100 py-1.5 text-[12px] last:border-0">
              <span className="shrink-0 rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] font-medium text-neutral-700">{i.kindKo}</span>
              <span className="min-w-0 flex-1 truncate text-text-primary" title={ISSUE_TEXT(i)}>
                {ISSUE_TEXT(i)}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-text-secondary">열린 문제가 없습니다.</p>
      );
    case "shared_docs":
      return (d.shares ?? []).length ? (
        <div className="flex flex-col">
          {(d.shares ?? []).map((s) => (
            <button key={s.id} type="button" onClick={() => (s.itemKind === "doc" ? ws.nav.openReport(s.itemId) : ws.nav.view("documents"))} className="flex cursor-pointer items-center gap-2 py-1.5 text-left text-[13px] hover:text-primary">
              <FileText className="size-3.5 shrink-0 text-neutral-500" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{s.title}</span>
              <span className="shrink-0 text-[11px] text-text-secondary">{s.from.name}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-text-secondary">받은 것이 없습니다.</p>
      );
    case "routine_docs":
      return (d.docs ?? []).length ? (
        <div className="flex flex-col">
          {(d.docs ?? []).map((x) => (
            <button key={x.id} type="button" onClick={() => ws.nav.openReport(x.id)} className="flex cursor-pointer items-center gap-2 py-1.5 text-left text-[13px] hover:text-primary">
              <FileText className="size-3.5 shrink-0 text-neutral-500" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{x.title}</span>
              <span className="shrink-0 text-[11px] text-text-secondary">{when(x.updatedAt)}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-text-secondary">아직 없습니다.</p>
      );
    case "tasks":
      return (d.tasks ?? []).length ? (
        <div className="flex flex-col">
          {(d.tasks ?? []).map((t) => (
            <button key={t.id} type="button" onClick={() => ws.nav.view("tasks")} className="flex cursor-pointer items-center gap-2 py-1.5 text-left text-[13px] hover:text-primary">
              <ListChecks className="size-3.5 shrink-0 text-neutral-500" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{t.title}</span>
              <span className="shrink-0 text-[11px] text-text-secondary">{t.due}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-text-secondary">남은 할 일이 없습니다.</p>
      );
    case "assumptions":
      return (d.items ?? []).length ? (
        <div className="flex flex-col">
          {(d.items ?? []).map((a) => (
            <button key={a.id} type="button" onClick={() => openAssumption({ docKind: a.docKind ?? "report", docRef: a.docRef, title: a.docTitle, focusId: a.id })} className="flex cursor-pointer flex-col gap-0.5 border-b border-neutral-100 py-1.5 text-left last:border-0 hover:bg-neutral-50">
              <span className="truncate text-[13px] text-text-primary">
                {a.roleKo === "재심의 조건" && <span className="mr-1 text-text-secondary">재심의 조건</span>}“{a.quote}”
              </span>
              <span className="truncate text-[11px] text-text-secondary">
                {a.condition}
                {a.value && ` · 지금 ${a.value}`}
                {a.result && ` · ${a.result}`}
                {a.changed && " · 바뀜"} · {a.docTitle}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-text-secondary">감시 중인 가정이 없습니다.</p>
      );
    case "kpi":
      return (
        <div className="grid grid-cols-2 gap-2">
          {(d.metrics ?? []).map((m) => (
            <div key={m.id} className="rounded-2xl bg-neutral-50 px-3 py-2.5">
              <p className="text-[11px] text-text-secondary">{m.label}</p>
              <p className="num text-[18px] font-bold text-text-primary">{m.value}</p>
            </div>
          ))}
        </div>
      );
    case "houseview": {
      const hv = d.houseview;
      if (!hv || !hv.periods.length) return <p className="text-[13px] text-text-secondary">{hv?.pending ? "하우스뷰 문서를 읽는 중입니다." : "하우스뷰 문서가 없습니다(이름에 '하우스뷰')."}</p>;
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-[11px] text-text-secondary">
                <th className="py-1 pr-3 text-left font-medium">자산군</th>
                {hv.periods.map((p) => (
                  <th key={p} className="px-2 py-1 text-left font-medium">
                    <button type="button" onClick={() => openSource(hv.docs[p].docId)} title={hv.docs[p].title} className="cursor-pointer hover:text-primary">
                      {p}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {hv.rows.map((r) => (
                <tr key={r.asset} className="border-t border-neutral-100">
                  <td className="py-1.5 pr-3 text-text-primary">{r.asset}</td>
                  {hv.periods.map((p) => {
                    const c = r.cells[p];
                    return (
                      <td key={p} className="px-2 py-1.5">
                        {c ? (
                          <button type="button" onClick={() => openSource(c.docId, c.chunk)} title={c.quote} className="cursor-pointer hover:text-primary">
                            {c.changed && <span className="mr-0.5 text-text-secondary">→</span>}
                            {c.stanceKo}
                          </button>
                        ) : (
                          <span className="text-text-secondary">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {hv.assumptions.length > 0 && (
            <div className="mt-3 border-t border-neutral-100 pt-2">
              {hv.assumptions.map((a) => (
                <button key={a.id} type="button" onClick={() => openAssumption({ docKind: "data", docRef: a.docRef, title: a.period, focusId: a.id })} className="block w-full cursor-pointer truncate py-0.5 text-left text-[12px] hover:text-primary">
                  {a.period} 가정 “{a.quote}” · {a.condition}
                  {a.value && ` · 지금 ${a.value}`}
                  {a.result && <b className="font-semibold"> · {a.result}</b>}
                </button>
              ))}
            </div>
          )}
        </div>
      );
    }
    case "note":
      return <p className="whitespace-pre-wrap text-[13px] leading-6 text-text-primary">{d.text}</p>;
    case "peer_board":
      return d.peer ? <PeerBoard data={d.peer} /> : null;
    default:
      return (
        <p className="flex items-center gap-1.5 text-[13px] text-text-secondary">
          <AlertCircle className="size-4" aria-hidden />
          모르는 위젯
        </p>
      );
  }
}
