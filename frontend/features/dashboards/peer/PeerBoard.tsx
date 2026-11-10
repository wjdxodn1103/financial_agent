"use client";

/**
 * 피어 비교(대시보드 양식 peer) — 회사 카드 · 핵심 지표 대조(좌우 막대) · 분기 영업이익 · 주가 상대수익률 · 산업 전망 + '관련 뉴스·리포트' 탭.
 * 값은 서버가 계산한다(BE app/dashboards/peer.py). 숫자·문장을 누르면 원문 창(useOpenSource), 뉴스는 원문 기사 링크.
 */
import { useState } from "react";
import { ExternalLink, FileText, Newspaper } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOpenSource } from "../../workspace/sourceHost";
import { GroupedBars, LineChart, PALETTE } from "../charts";
import type { PeerBoardData, PeerCite, PeerCompany, PeerDoc, PeerValue } from "../types";

const signed = (v: number | null | undefined, digits = 1) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`);
const tone = (v: number | null | undefined) => (v == null || v === 0 ? "text-text-secondary" : v > 0 ? "text-destructive" : "text-primary");
const CARD = "min-w-0 rounded-[24px] bg-white px-5 py-4";
const tip = (v: { calc?: string; cites: PeerCite[] }) => [v.calc && `계산: ${v.calc}`, ...v.cites.map((c) => c.label)].filter(Boolean).join("\n");

function useCite() {
  const open = useOpenSource();
  return (c?: PeerCite | null) => c && open(c.docId, c.chunk || null, c.cell ?? null);
}

function CompanyCard({ c, color }: { c: PeerCompany; color: string }) {
  const cite = useCite();
  const r = c.returns;
  return (
    <section className={cn(CARD, "flex flex-wrap items-center gap-x-5 gap-y-3")}>
      <span className="size-10 shrink-0 rounded-2xl" style={{ background: color }} aria-hidden />
      <div className="min-w-0">
        <p className="text-[17px] leading-tight font-bold text-text-primary">
          {c.name} <span className="num text-[12px] font-medium text-text-secondary">{c.code}</span>
        </p>
        {c.close != null && (
          <p className="num text-[22px] leading-tight font-bold text-text-primary">
            {c.close.toLocaleString("ko-KR")}
            <span className={cn("ml-1.5 text-[13px] font-semibold", tone(c.changePct))}>{signed(c.changePct, 2)}</span>
          </p>
        )}
      </div>
      <dl className="num ml-auto flex gap-5 text-[14px] font-bold text-text-primary">
        {c.marketCap && (
          <div>
            <dt className="text-[11px] font-medium text-text-secondary">시가총액</dt>
            <dd>
              <button type="button" title={tip(c.marketCap)} onClick={() => cite(c.marketCap?.cites[0])} className="cursor-pointer hover:text-primary">
                {c.marketCap.display}
              </button>
            </dd>
          </div>
        )}
        {(["m1", "m3", "m12"] as const).map((k) => (
          <div key={k}>
            <dt className="text-[11px] font-medium text-text-secondary">{{ m1: "1M", m3: "3M", m12: "12M" }[k]}</dt>
            <dd className={tone(r?.[k])}>{signed(r?.[k])}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Value({ v, align }: { v: PeerValue | null; align: "left" | "right" }) {
  const cite = useCite();
  if (!v) return <span className="w-16 text-center text-[13px] text-neutral-400">–</span>;
  return (
    <button
      type="button"
      title={tip(v)}
      onClick={() => cite(v.cites[0])}
      className={cn("num w-16 shrink-0 text-[14px] font-bold text-text-primary", align === "right" ? "text-right" : "text-left", v.cites.length ? "cursor-pointer hover:text-primary" : "cursor-default")}
    >
      {v.display}
    </button>
  );
}

/** 지표마다 두 회사를 좌우로 맞댄다 — 막대 길이는 두 값 가운데 큰 쪽이 기준(음수는 막대 없이 값만). */
function MirrorBars({ data }: { data: PeerBoardData }) {
  const [a, b] = data.companies;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-[14px] font-bold">
        <span style={{ color: PALETTE[0] }}>{a.name}</span>
        <span style={{ color: PALETTE[1] }}>{b.name}</span>
      </div>
      {data.metrics.map((m) => {
        const [va, vb] = m.values;
        const top = Math.max(Math.abs(va?.value ?? 0), Math.abs(vb?.value ?? 0)) || 1;
        const w = (v: PeerValue | null) => `${v && v.value > 0 ? Math.max(2, (v.value / top) * 100) : 0}%`;
        return (
          <div key={m.id} className="flex items-center gap-2 py-[9px]">
            <Value v={va} align="right" />
            <div className="flex min-w-0 flex-1 justify-end">
              <span className="h-[22px] rounded-l-md" style={{ width: w(va), background: PALETTE[0] }} />
            </div>
            <span className="w-[136px] shrink-0 text-center text-[12px] leading-tight font-semibold text-text-secondary">
              {m.label}
              {m.unit && m.unit !== "%" && <span className="font-normal"> · {m.unit}</span>}
            </span>
            <div className="flex min-w-0 flex-1">
              <span className="h-[22px] rounded-r-md" style={{ width: w(vb), background: PALETTE[1] }} />
            </div>
            <Value v={vb} align="left" />
          </div>
        );
      })}
    </div>
  );
}

/** 회사가 셋이면 좌우 대조 대신 표. */
function MetricTable({ data }: { data: PeerBoardData }) {
  return (
    <table className="num w-full text-[13px]">
      <thead>
        <tr className="text-[12px] text-text-secondary">
          <th className="py-1.5 text-left font-semibold">지표</th>
          {data.companies.map((c, i) => (
            <th key={c.ticker} className="py-1.5 text-right font-bold" style={{ color: PALETTE[i % PALETTE.length] }}>
              {c.name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.metrics.map((m) => (
          <tr key={m.id} className="border-t border-neutral-100">
            <td className="py-2 text-left text-text-secondary">
              {m.label}
              {m.unit && m.unit !== "%" && ` · ${m.unit}`}
            </td>
            {m.values.map((v, i) => (
              <td key={i} className="py-2">
                <span className="flex justify-end">
                  <Value v={v} align="right" />
                </span>
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Outlook({ data }: { data: PeerBoardData }) {
  const cite = useCite();
  if (!data.outlook.length) return null;
  return (
    <section className={cn(CARD, "lg:col-span-12")}>
      <h2 className="mb-3 text-[15px] font-bold text-text-primary">산업 전망</h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {data.outlook.map((o, i) => (
          <div key={i} className="rounded-2xl bg-neutral-50 px-4 py-3">
            <p className="text-[13px] font-bold text-text-primary">{o.title}</p>
            <p className="mt-1 text-[13px] leading-[1.55] text-neutral-700">
              {o.text}{" "}
              {o.cites.map((c, k) => (
                <button key={k} type="button" title={c.label} onClick={() => cite(c)} className="mx-0.5 cursor-pointer rounded-md bg-primary-soft px-1.5 text-[11px] font-bold text-primary">
                  {c.label.length > 14 ? `${c.label.slice(0, 13)}…` : c.label || "근거"}
                </button>
              ))}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

function DocList({ title, icon, rows, external }: { title: string; icon: React.ReactNode; rows: PeerDoc[]; external?: boolean }) {
  const open = useOpenSource();
  return (
    <section className={CARD}>
      <h2 className="mb-2 flex items-center gap-1.5 text-[15px] font-bold text-text-primary">
        {icon}
        {title}
        <span className="num text-[12px] font-medium text-text-secondary">{rows.length}</span>
      </h2>
      {rows.length === 0 && <p className="py-6 text-center text-[13px] text-text-secondary">아직 붙은 자료가 없습니다.</p>}
      <ul>
        {rows.map((d) => (
          <li key={d.docId} className="flex items-center gap-2 border-t border-neutral-100 py-2 first:border-t-0">
            <button type="button" onClick={() => open(d.docId)} className="min-w-0 flex-1 cursor-pointer text-left">
              <p className="truncate text-[13px] font-semibold text-text-primary hover:text-primary">{d.title}</p>
              <p className="num truncate text-[11px] text-text-secondary">
                {[d.issuer, d.date, d.company, d.pages ? `${d.pages}쪽` : ""].filter(Boolean).join(" · ")}
              </p>
            </button>
            {external && d.url && (
              <a href={d.url} target="_blank" rel="noreferrer" aria-label="원문 기사 열기" className="flex size-8 shrink-0 items-center justify-center rounded-lg text-neutral-500 hover:bg-neutral-100">
                <ExternalLink className="size-4" aria-hidden />
              </a>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function PeerBoard({ data }: { data: PeerBoardData }) {
  const cite = useCite();
  const [tab, setTab] = useState<"compare" | "docs">("compare");
  if (data.error) return <p className="rounded-[24px] bg-white px-5 py-6 text-[13px] text-text-secondary">{data.error}</p>;
  const nDocs = data.docs.news.length + data.docs.reports.length;
  const q = data.quarters;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-1 self-start rounded-xl bg-white p-1 text-[13px] font-semibold">
        {(
          [
            ["compare", "지표 비교"],
            ["docs", `관련 뉴스·리포트 ${nDocs}`],
          ] as const
        ).map(([k, label]) => (
          <button key={k} type="button" onClick={() => setTab(k)} className={cn("cursor-pointer rounded-lg px-3 py-1.5", tab === k ? "bg-primary-soft text-primary" : "text-text-secondary hover:text-text-primary")}>
            {label}
          </button>
        ))}
      </div>
      <div className={cn("grid grid-cols-1 gap-3", data.companies.length === 2 ? "md:grid-cols-2" : "md:grid-cols-3")}>
        {data.companies.map((c, i) => (
          <CompanyCard key={c.ticker} c={c} color={PALETTE[i % PALETTE.length]} />
        ))}
      </div>
      {tab === "compare" ? (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
          <section className={cn(CARD, "lg:col-span-7")}>
            <h2 className="mb-3 text-[15px] font-bold text-text-primary">
              핵심 지표 대조 <span className="text-[12px] font-medium text-text-secondary">{data.period}</span>
            </h2>
            {data.companies.length === 2 ? <MirrorBars data={data} /> : <MetricTable data={data} />}
            <p className="mt-3 text-[11px] leading-5 text-text-secondary">
              자료: DART 정기보고서({data.basis}) · Yahoo Finance 종가({data.priceDate}) — 숫자를 누르면 원문 칸이 열립니다
              {data.missing.length > 0 && ` · 재무 자료 없음: ${data.missing.join(", ")}`}
            </p>
          </section>
          <div className="flex min-w-0 flex-col gap-3 lg:col-span-5">
            {q && (
              <section className={CARD}>
                <h2 className="mb-2 text-[15px] font-bold text-text-primary">
                  분기 영업이익 추이 <span className="text-[12px] font-medium text-text-secondary">({q.unit})</span>
                </h2>
                <GroupedBars categories={q.categories} series={q.series} height={190} onPick={(s, c) => cite(q.series[s].points[c])} />
              </section>
            )}
            {data.relative && (
              <section className={CARD}>
                <h2 className="mb-2 text-[15px] font-bold text-text-primary">
                  주가 상대수익률 <span className="text-[12px] font-medium text-text-secondary">({data.relative.base} = 100)</span>
                </h2>
                <LineChart series={data.relative.series} height={170} />
              </section>
            )}
          </div>
          <Outlook data={data} />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <DocList title="뉴스" icon={<Newspaper className="size-4 text-primary" aria-hidden />} rows={data.docs.news} external />
          <div className="flex min-w-0 flex-col gap-3">
            <DocList title="증권사 리포트" icon={<FileText className="size-4 text-primary" aria-hidden />} rows={data.docs.reports} />
            <DocList title="공시" icon={<FileText className="size-4 text-neutral-500" aria-hidden />} rows={data.docs.filings} external />
          </div>
        </div>
      )}
    </div>
  );
}
