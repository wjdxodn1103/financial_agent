"use client";

/**
 * 관리 ▸ 품질·이용(관리자만, RFP SFR-001) — 지표 8개(누르면 원자료 줄), 이용 현황(기능·워크스페이스별), 날짜별 추이, 평가 세트 [지금 평가].
 * 값은 BE app/quality/kpi.py 가 코드로 계산한다(LLM 0회). 원자료 줄을 누르면 그 문서·소스로 간다.
 */
import { useEffect, useState } from "react";
import { Loader2, Play } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { jsonInit, req } from "../report/api";
import { LineChart } from "../dashboards/charts";
import { useWorkspace } from "../workspace/context";
import { PageHeader } from "../workspace/components/views/PageHeader";

interface Trace { kind: string; id?: string | null; ws?: string; label: string; detail: string; step?: string }
interface Metric { id: string; label: string; value: number | null; display: string; detail: string; trace: Trace[] }
interface Quality {
  days: number;
  at: string;
  metrics: Metric[];
  usage: {
    activeUsers: number; turns: number; docs: number; routineRuns: number; sourceRuns: number; llmCalls: number; tokens: number;
    byFeature: { feature: string; calls: number; tokens: number }[];
    byWorkspace: { workspaceId: string; calls: number }[];
    trend: { date: string; turns: number; docs: number; llmCalls: number }[];
  };
  evals: { at: string; qa: { correct: number; total: number }; assumption: { correct: number; total: number } }[];
}

const DAYS = [7, 30, 90];

export function QualityView() {
  const ws = useWorkspace();
  const [days, setDays] = useState(7);
  const [q, setQ] = useState<Quality | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = (d: number) => req<Quality>(`/api/admin/quality?days=${d}`).then(setQ, () => toast.error("불러오지 못했습니다.", { position: "top-center" }));
  useEffect(() => {
    void load(days);
  }, [days]); // eslint-disable-line react-hooks/exhaustive-deps

  const evalNow = async () => {
    setBusy(true);
    try {
      const r = await req<{ qa: { correct: number; total: number }; assumption: { correct: number; total: number } }>("/api/admin/quality/eval", jsonInit("POST", {}));
      toast.success(`평가: 질의 ${r.qa.correct}/${r.qa.total} · 가정 판정 ${r.assumption.correct}/${r.assumption.total}`, { position: "top-center" });
      await load(days);
    } catch {
      toast.error("평가하지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  const go = (t: Trace) => {
    if ((t.kind === "report" || t.kind === "section") && t.id) ws.nav.openReport(t.id);
    else if (t.kind === "source" && t.id) ws.nav.view("sources");
    else if (t.kind === "series" || t.kind === "issue") ws.nav.view("dataStatus");
  };

  const u = q?.usage;
  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
      <PageHeader
        title="품질·이용"
        wide
        desc={q ? `최근 ${q.days}일 · ${new Date(q.at).toLocaleString("ko-KR")}` : undefined}
        actions={
          <>
            <div className="flex items-center gap-0.5 rounded-xl bg-white p-1">
              {DAYS.map((d) => (
                <button key={d} type="button" onClick={() => setDays(d)} className={cn("h-8 cursor-pointer rounded-lg px-3 text-[13px]", d === days ? "bg-neutral-100 font-semibold text-text-primary" : "text-text-secondary")}>
                  {d}일
                </button>
              ))}
            </div>
            <button type="button" disabled={busy} onClick={() => void evalNow()} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />}
              {busy ? "평가 중…" : "지금 평가"}
            </button>
          </>
        }
      />
      <div className="mx-auto max-w-[1180px] px-8 pb-14">
        {!q && <p className="text-[13px] text-text-secondary">불러오는 중…</p>}
        {q && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {q.metrics.map((m) => (
                <button key={m.id} type="button" onClick={() => setOpen(open === m.id ? null : m.id)} className={cn("cursor-pointer rounded-[20px] bg-white px-5 py-4 text-left hover:ring-1 hover:ring-neutral-300", open === m.id && "ring-2 ring-primary")}>
                  <p className="text-[13px] text-text-secondary">{m.label}</p>
                  <p className="num mt-1 text-[24px] font-bold text-text-primary">{m.display}</p>
                  <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-text-secondary">{m.detail}</p>
                </button>
              ))}
            </div>
            {open && (
              <div className="mt-3 rounded-[20px] bg-white px-5 py-4">
                <p className="text-[14px] font-semibold text-text-primary">{q.metrics.find((m) => m.id === open)?.label} — 원자료</p>
                {(q.metrics.find((m) => m.id === open)?.trace ?? []).length === 0 && <p className="mt-2 text-[13px] text-text-secondary">보일 줄이 없습니다.</p>}
                {(q.metrics.find((m) => m.id === open)?.trace ?? []).map((t, i) => (
                  <button key={i} type="button" onClick={() => go(t)} className="flex w-full cursor-pointer items-center gap-3 border-b border-neutral-100 py-2 text-left text-[13px] last:border-0 hover:bg-neutral-50">
                    <span className="min-w-0 flex-1 truncate text-text-primary">{t.label}</span>
                    <span className="shrink-0 text-text-secondary tabular-nums">{t.detail}</span>
                  </button>
                ))}
              </div>
            )}
            {u && (
              <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
                <section className="rounded-[20px] bg-white px-5 py-4">
                  <p className="text-[14px] font-semibold text-text-primary">이용 추이</p>
                  <div className="mt-2 grid grid-cols-3 gap-2 text-[12px] text-text-secondary sm:grid-cols-6">
                    {[
                      ["활성 사용자", u.activeUsers],
                      ["대화 턴", u.turns],
                      ["문서 생성", u.docs],
                      ["루틴 실행", u.routineRuns],
                      ["수집 실행", u.sourceRuns],
                      ["LLM 호출", u.llmCalls],
                    ].map(([k, v]) => (
                      <div key={k as string} className="rounded-xl bg-neutral-50 px-3 py-2">
                        {k}
                        <b className="num block text-[16px] text-text-primary">{(v as number).toLocaleString()}</b>
                      </div>
                    ))}
                  </div>
                  {u.trend.length > 1 && (
                    <div className="mt-3">
                      <LineChart
                        height={180}
                        series={[
                          { name: "LLM 호출", points: u.trend.map((t) => ({ date: t.date, value: t.llmCalls })) },
                          { name: "대화 턴", points: u.trend.map((t) => ({ date: t.date, value: t.turns })) },
                        ]}
                      />
                    </div>
                  )}
                </section>
                <section className="rounded-[20px] bg-white px-5 py-4">
                  <p className="text-[14px] font-semibold text-text-primary">기능별 LLM 이용 · 토큰 {u.tokens.toLocaleString()}</p>
                  <div className="mt-2">
                    {u.byFeature.map((f) => (
                      <div key={f.feature} className="flex items-center gap-3 border-b border-neutral-100 py-1.5 text-[13px] last:border-0">
                        <span className="min-w-0 flex-1 truncate">{f.feature}</span>
                        <span className="num shrink-0 text-text-secondary">{f.calls.toLocaleString()}회</span>
                        <span className="num w-24 shrink-0 text-right text-text-secondary">{f.tokens.toLocaleString()}</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-4 text-[14px] font-semibold text-text-primary">평가 기록</p>
                  {q.evals.length === 0 && <p className="mt-1 text-[13px] text-text-secondary">아직 없습니다.</p>}
                  {q.evals.slice(0, 6).map((e) => (
                    <p key={e.at} className="flex gap-3 py-1 text-[13px]">
                      <span className="text-text-secondary tabular-nums">{e.at.slice(0, 16).replace("T", " ")}</span>
                      <span>
                        질의 {e.qa.correct}/{e.qa.total} · 가정 판정 {e.assumption.correct}/{e.assumption.total}
                      </span>
                    </p>
                  ))}
                </section>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
