"use client";

/**
 * 시장 홈 — 금융 데이터 AI 에이전트의 기본 화면(네이버 증권·야후 파이낸스 참고, 2026-11-03).
 * 주요 지수 카드 · 큰 차트(고른 종목, 1개월~1년) · 환율·원자재·금리 목록. 숫자는 서버가 계산(app/market/home.py), 변화는 ▲▼ 기호와 숫자로만(판정 색 없음).
 * 카드·목록 줄을 누르면 큰 차트가 그 종목으로 바뀐다. 지수·환율·원자재는 Yahoo(지연·시연용), 금리는 FRED·미 재무부.
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { SeriesCard } from "../data/types";
import { getMarketHome, getMarketHomeChart, refreshMarketHome } from "./api";
import { LineChart, Sparkline } from "./charts";
import type { MarketChartView, MarketHomeView, MarketQuote } from "./types";

const RANGES = ["1M", "3M", "6M", "1Y"] as const;
type Range = (typeof RANGES)[number];
const RANGE_KO: Record<Range, string> = { "1M": "1개월", "3M": "3개월", "6M": "6개월", "1Y": "1년" };

const arrow = (v: number | null | undefined) => (v == null ? "" : v > 0 ? "▲" : v < 0 ? "▼" : "");
const num = (v: number | null | undefined, d: number) => (v == null ? "—" : v.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d }));
const signed = (v: number | null, d: number) => (v == null ? "" : `${v > 0 ? "+" : ""}${num(v, d)}`);

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function Change({ q, className }: { q: MarketQuote; className?: string }) {
  if (q.change == null) return <span className={cn("text-text-secondary", className)}>—</span>;
  return (
    <span className={cn("num text-text-secondary", className)}>
      {arrow(q.change)} {num(Math.abs(q.change), q.decimals)} ({signed(q.pct, 2)}%)
    </span>
  );
}

function IndexCard({ q, active, onPick }: { q: MarketQuote; active: boolean; onPick: (t: string) => void }) {
  return (
    <button type="button" onClick={() => onPick(q.ticker)} className={cn("flex min-w-0 cursor-pointer flex-col gap-1 overflow-hidden rounded-2xl px-4 py-3 text-left", active ? "bg-primary-soft" : "bg-neutral-50 hover:bg-neutral-100")}>
      <span className="truncate text-[13px] font-semibold text-text-primary">{q.name}</span>
      <span className="num truncate text-[20px] leading-tight font-bold text-text-primary">{num(q.value, q.decimals)}</span>
      <span className="flex items-end justify-between gap-2">
        <span className="flex min-w-0 flex-col">
          <Change q={q} className="text-[12px]" />
          <span className="num text-[11px] text-neutral-400">{q.date ?? ""}</span>
        </span>
        <Sparkline values={q.spark} width={72} height={26} className="shrink-0" />
      </span>
    </button>
  );
}

function QuoteRow({ q, active, onPick }: { q: MarketQuote; active: boolean; onPick: (t: string) => void }) {
  return (
    <button type="button" onClick={() => onPick(q.ticker)} className={cn("grid w-full cursor-pointer grid-cols-[1fr_auto_auto] items-center gap-3 rounded-xl px-3 py-2 text-left", active ? "bg-primary-soft" : "hover:bg-neutral-50")}>
      <span className="min-w-0 truncate text-[13px] font-semibold text-text-primary">
        {q.name}
        <span className="ml-1 text-[11px] font-normal text-neutral-400">{q.unit}</span>
      </span>
      <span className="num text-[14px] font-bold text-text-primary">{num(q.value, q.decimals)}</span>
      <Change q={q} className="w-[124px] text-right text-[12px]" />
    </button>
  );
}

function RateRow({ c }: { c: SeriesCard }) {
  const d1 = c.changes.d1;
  return (
    <div className="grid grid-cols-[1fr_auto_auto] items-center gap-3 rounded-xl px-3 py-2">
      <span className="min-w-0 truncate text-[13px] font-semibold text-text-primary">{c.name}</span>
      <span className="num text-[14px] font-bold text-text-primary">
        {c.display ?? "—"}
        <span className="ml-0.5 text-[11px] font-medium text-text-secondary">{c.unit}</span>
      </span>
      <span className="num w-[64px] text-right text-[12px] text-text-secondary">{d1 ? `${arrow(d1.value)} ${d1.display.replace(/^[+-]/, "")}` : "—"}</span>
    </div>
  );
}

export function MarketHome() {
  const [v, setV] = useState<MarketHomeView | null>(null);
  const [pick, setPick] = useState("^KS11");
  const [range, setRange] = useState<Range>("3M");
  const [chart, setChart] = useState<MarketChartView | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setV(await getMarketHome());
    } catch {
      toast.error("시장 홈을 불러오지 못했습니다.", { position: "top-center" });
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  // 뒤에서 시세를 받는 중이면 잠시 뒤 다시 읽는다
  useEffect(() => {
    if (!v?.refreshing) return;
    const t = window.setTimeout(() => void load(), 15000);
    return () => window.clearTimeout(t);
  }, [v, load]);
  useEffect(() => {
    let off = false;
    getMarketHomeChart(pick, range)
      .then((c) => !off && setChart(c))
      .catch(() => !off && setChart(null));
    return () => {
      off = true;
    };
  }, [pick, range, v?.fetchedAt]);

  const refresh = async () => {
    setBusy(true);
    try {
      await refreshMarketHome();
      toast.success("시세를 다시 받고 있습니다. 잠시 뒤 새로 고쳐집니다.", { position: "top-center" });
      window.setTimeout(() => void load(), 20000);
    } catch {
      toast.error("시세를 다시 받지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  if (!v) return <Loader2 className="mx-auto my-16 size-6 animate-spin text-neutral-400" />;
  const all = v.groups.flatMap((g) => g.items);
  const group = (k: string) => v.groups.find((g) => g.key === k)?.items ?? [];
  const indices = [...group("kr"), ...group("global")];
  const cur = all.find((q) => q.ticker === pick);
  const tabs = v.main.includes(pick) ? v.main : [...v.main, pick];
  const empty = all.every((q) => q.value == null);

  return (
    <div className="mx-auto grid max-w-[1280px] grid-cols-1 gap-3 px-8 pb-3 lg:grid-cols-12">
      <div className="flex flex-wrap items-center justify-between gap-2 lg:col-span-12">
        <p className="text-[12px] text-text-secondary">
          {v.source} · 금리 FRED·미 재무부{v.fetchedAt && ` · 받은 시각 ${when(v.fetchedAt)}`}
          {v.refreshing && (
            <span className="ml-2 inline-flex items-center gap-1 text-primary">
              <Loader2 className="size-3 animate-spin" aria-hidden />
              시세를 받는 중
            </span>
          )}
        </p>
        <button type="button" disabled={busy || v.refreshing} onClick={() => void refresh()} className="flex h-9 cursor-pointer items-center gap-1.5 rounded-xl bg-white px-3 text-[13px] font-semibold text-neutral-700 hover:bg-neutral-50 disabled:opacity-50">
          <RefreshCw className="size-4" aria-hidden />
          시세 다시 받기
        </button>
      </div>

      {empty && <p className="rounded-[24px] bg-white px-5 py-6 text-center text-[13px] text-text-secondary lg:col-span-12">시세를 처음 받고 있습니다. 잠시 뒤 채워집니다.</p>}

      <section className="min-w-0 rounded-[24px] bg-white px-5 py-4 lg:col-span-12">
        <h2 className="mb-3 text-[15px] font-bold text-text-primary">주요 지수</h2>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {indices.map((q) => (
            <IndexCard key={q.ticker} q={q} active={q.ticker === pick} onPick={setPick} />
          ))}
        </div>
      </section>

      <section className="min-w-0 rounded-[24px] bg-white px-5 py-4 lg:col-span-8">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-1">
            {tabs.map((t) => {
              const q = all.find((x) => x.ticker === t);
              return (
                q && (
                  <button key={t} type="button" onClick={() => setPick(t)} className={cn("cursor-pointer rounded-lg px-3 py-1.5 text-[13px] font-semibold", t === pick ? "bg-primary-soft text-primary" : "text-text-secondary hover:bg-neutral-50")}>
                    {q.name}
                  </button>
                )
              );
            })}
          </div>
          <div className="flex rounded-xl bg-neutral-100 p-1">
            {RANGES.map((r) => (
              <button key={r} type="button" onClick={() => setRange(r)} className={cn("cursor-pointer rounded-lg px-2.5 py-1 text-[12px] font-semibold", range === r ? "bg-white text-text-primary shadow-sm" : "text-text-secondary")}>
                {RANGE_KO[r]}
              </button>
            ))}
          </div>
        </div>
        {cur && (
          <div className="mb-1 flex flex-wrap items-end gap-x-3 gap-y-1">
            <span className="text-[15px] font-bold text-text-primary">{cur.name}</span>
            <span className="num text-[24px] leading-tight font-bold text-text-primary">{num(cur.value, cur.decimals)}</span>
            <span className="text-[12px] text-text-secondary">{cur.unit}</span>
            <Change q={cur} className="text-[13px]" />
          </div>
        )}
        {cur && cur.high52 != null && (
          <p className="num mb-2 text-[12px] text-text-secondary">
            52주 최고 {num(cur.high52, cur.decimals)} · 최저 {num(cur.low52, cur.decimals)} · {cur.date} 기준
          </p>
        )}
        {chart ? <LineChart series={[{ name: chart.name, points: chart.points, decimals: chart.decimals, unit: chart.unit }]} height={240} /> : <Loader2 className="mx-auto my-16 size-5 animate-spin text-neutral-400" />}
      </section>

      <section className="min-w-0 rounded-[24px] bg-white px-5 py-4 lg:col-span-4">
        <h2 className="mb-2 text-[15px] font-bold text-text-primary">환율</h2>
        <div className="flex flex-col">
          {group("fx").map((q) => (
            <QuoteRow key={q.ticker} q={q} active={q.ticker === pick} onPick={setPick} />
          ))}
        </div>
      </section>

      <section className="min-w-0 rounded-[24px] bg-white px-5 py-4 lg:col-span-8">
        <h2 className="mb-2 text-[15px] font-bold text-text-primary">원자재·선물</h2>
        <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
          {group("cmd").map((q) => (
            <QuoteRow key={q.ticker} q={q} active={q.ticker === pick} onPick={setPick} />
          ))}
        </div>
      </section>

      <section className="min-w-0 rounded-[24px] bg-white px-5 py-4 lg:col-span-4">
        <h2 className="mb-2 text-[15px] font-bold text-text-primary">금리</h2>
        <div className="flex flex-col">
          {v.rates.map((c) => (
            <RateRow key={c.id} c={c} />
          ))}
        </div>
      </section>
    </div>
  );
}
