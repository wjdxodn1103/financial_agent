"use client";

/**
 * 홈 — 기본은 마이페이지 대시보드(MyPage: 할 일·일정·검토 요청·내 문서·내가 한 일).
 * FEATURES.briefing 을 켜면 예전 브리핑: 큰 숫자 카드(미해결 충돌·확인 기다리는 기록·내 할 일·리포트) + "지난 접속 이후" 소식
 * (결정적으로 모은다, LLM 없음. 방문 단위로 기준 시각이 고정된다 — BE briefing.py).
 */
import { useEffect, useState, type ComponentType } from "react";
import { AtSign, ChevronRight, ClipboardCheck, Clock, FileDown, FileText, FolderOpen, ListTodo, Loader2, MessagesSquare, Quote } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SessionListItem } from "../../../report/types";
import { downloadProgressDoc, getBriefing, getLedger, listReports } from "../../api";
import { useWorkspace } from "../../context";
import { FEATURES } from "../../features";
import type { Briefing, WorkspaceView } from "../../types";
import { MyPage } from "./MyPage";

function when(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function Metric({ label, value, unit, tone, sub, onClick }: { label: string; value: number | string; unit?: string; tone?: "danger" | "accent"; sub?: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="group cursor-pointer rounded-2xl bg-neutral-50 px-5 py-4 text-left transition-colors hover:bg-neutral-100">
      <span className="flex items-center justify-between text-[13px] font-medium text-text-secondary">
        {label}
        <ChevronRight className="size-4 text-neutral-400 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
      </span>
      <span className={cn("num mt-1.5 block text-[28px] leading-tight font-bold", tone === "danger" ? "text-[#f04452]" : tone === "accent" ? "text-primary" : "text-text-primary")}>
        {value}
        {unit && <span className="ml-0.5 text-[18px] font-semibold">{unit}</span>}
      </span>
      {sub && <span className="mt-1 block truncate text-[12px] text-text-secondary">{sub}</span>}
    </button>
  );
}

function Row({ icon: Icon, tone, children, meta, onClick }: { icon: ComponentType<{ className?: string }>; tone: string; children: React.ReactNode; meta?: string; onClick?: () => void }) {
  const body = (
    <>
      <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-full", tone)}>
        <Icon className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] leading-6 text-text-primary">{children}</span>
        {meta && <span className="block text-[12px] text-text-secondary">{meta}</span>}
      </span>
      {onClick && <ChevronRight className="size-4 shrink-0 text-neutral-400" aria-hidden />}
    </>
  );
  return onClick ? (
    <button type="button" onClick={onClick} className="flex w-full cursor-pointer items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors hover:bg-neutral-50">
      {body}
    </button>
  ) : (
    <div className="flex items-center gap-3 px-3 py-3">{body}</div>
  );
}

export function HomeView() {
  return FEATURES.briefing ? <BriefingHome /> : <MyPage />;
}

/** 브리핑 홈(FEATURES.briefing) — 지표 카드·'지난 접속 이후' 소식 */
function BriefingHome() {
  const ws = useWorkspace();
  const detail = ws.detail!;
  const [reports, setReports] = useState<SessionListItem[]>([]);
  const [brief, setBrief] = useState<Briefing | null>(null);
  const [conflicts, setConflicts] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listReports(ws.workspaceId)
      .then((x) => !cancelled && setReports(x))
      .catch(() => undefined);
    getBriefing(ws.workspaceId)
      .then((b) => !cancelled && setBrief(b))
      .catch(() => undefined);
    getLedger(ws.workspaceId)
      .then((l) => !cancelled && setConflicts(l.stats.conflicts))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [ws.workspaceId]);

  const progressDoc = async () => {
    setExporting(true);
    try {
      await downloadProgressDoc(ws.workspaceId);
    } catch {
      toast.error("경과 문서를 만들지 못했습니다.", { position: "top-center" });
    } finally {
      setExporting(false);
    }
  };

  const go = (v: WorkspaceView) => () => ws.nav.view(v);
  const pending = brief?.pendingRecords.length ?? 0;
  const myTasks = brief?.myTasks.length ?? 0;
  const todo = (conflicts ?? 0) + pending + myTasks;
  const news = brief ? brief.newRecords.length + brief.mentions.length + brief.reviews.length + brief.documents.length + brief.reports.length : 0;

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[960px] px-8 pt-9 pb-12">
        <div className="flex items-end justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[14px] font-medium text-text-secondary">{detail.workspace.name}</p>
            <h1 className="mt-1 text-[26px] leading-tight font-bold tracking-tight text-text-primary">
              {ws.me.name} {ws.me.title}님, {brief === null ? "불러오는 중이에요" : todo ? `확인할 게 ${todo}건 있어요` : "지금 확인할 건 없어요"}
            </h1>
            {detail.workspace.description && <p className="mt-1.5 text-[15px] text-text-secondary">{detail.workspace.description}</p>}
          </div>
          <Button variant="outline" size="sm" disabled={exporting} onClick={() => void progressDoc()} title="팀 기록·충돌 채택·검수·자료·작업을 날짜순으로 묶은 DOCX(AI 요약 없음)">
            {exporting ? <Loader2 className="animate-spin" aria-hidden /> : <FileDown aria-hidden />}
            경과 문서
          </Button>
        </div>

        <div className="mt-7 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="미해결 충돌" value={conflicts ?? "–"} unit={conflicts === null ? undefined : "건"} tone={conflicts ? "danger" : undefined} sub="자료마다 다른 숫자" onClick={go("ledger")} />
          <Metric label="확인 기다리는 기록" value={pending} unit="건" tone={pending ? "accent" : undefined} sub="확인하면 팀 기록" onClick={go("channel")} />
          <Metric label="내 할 일" value={myTasks} unit="건" sub={brief?.myTasks[0]?.title ?? "맡은 일 없음"} onClick={go("tasks")} />
          <Metric label="리포트" value={reports.length} unit="편" sub={reports[0] ? reports[0].title : "아직 없음"} onClick={() => ws.nav.openReport(null)} />
        </div>

        <section className="mt-9">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[19px] font-bold tracking-tight text-text-primary">{brief?.since ? "지난 접속 이후" : "이 워크스페이스 소식"}</h2>
            {brief?.since && <span className="text-[13px] text-text-secondary">{when(brief.since)} 이후 · {news}건</span>}
          </div>
          <div className="mt-2 flex flex-col">
            {brief && news === 0 && pending === 0 && <p className="px-3 py-6 text-[15px] text-text-secondary">새 소식이 없어요.</p>}
            {brief && pending > 0 && (
              <Row icon={MessagesSquare} tone="bg-violet-50 text-violet-700" meta="기록 비서가 대화에서 뽑은 결정·지시 후보" onClick={go("channel")}>
                확인을 기다리는 기록 후보 {pending}건
              </Row>
            )}
            {brief?.newRecords.map((r) => (
              <Row key={r.id} icon={Quote} tone="bg-primary-soft text-primary" meta={`${r.typeKo} · ${when(r.at)}`}>
                {r.author}님이 “{r.quote || r.text}”라고 남기셨어요
              </Row>
            ))}
            {brief?.mentions.map((m) => (
              <Row key={m.id} icon={AtSign} tone="bg-amber-50 text-amber-700" meta={when(m.at)} onClick={go("channel")}>
                {m.author}님이 불렀어요 — “{m.text}”
              </Row>
            ))}
            {brief?.reviews.map((r) => (
              <Row key={r.id} icon={ClipboardCheck} tone="bg-orange-50 text-orange-700" meta={`불일치 ${r.counts.mismatch ?? 0} · 계산 오류 ${r.counts.calc ?? 0} · 근거 없음 ${r.counts.unsourced ?? 0}`} onClick={go("reviews")}>
                {r.by}님이 “{r.docLabel}”를 검수했어요
              </Row>
            ))}
            {brief && brief.documents.length > 0 && (
              <Row icon={FolderOpen} tone="bg-neutral-100 text-neutral-600" meta={brief.documents.map((d) => `${d.label}(${d.by})`).join(", ")} onClick={go("documents")}>
                새 자료 {brief.documents.length}건
              </Row>
            )}
            {brief && brief.reports.length > 0 && (
              <Row icon={FileText} tone="bg-neutral-100 text-neutral-600" meta={brief.reports.map((r) => r.by).join(", ")} onClick={() => ws.nav.openReport(null)}>
                바뀐 리포트: {brief.reports.map((r) => r.title).join(", ")}
              </Row>
            )}
            {brief && myTasks > 0 && (
              <Row icon={ListTodo} tone="bg-emerald-50 text-emerald-700" meta={brief.myTasks.slice(0, 3).map((t) => `${t.title}${t.due ? ` ~${t.due}` : ""}`).join(" · ")} onClick={go("tasks")}>
                내 할 일 {myTasks}건
              </Row>
            )}
          </div>
          {brief?.lastRun && (
            <p className="mt-3 flex items-center gap-1.5 px-3 text-[12px] text-text-secondary">
              <Clock className="size-3.5" aria-hidden />
              기록 비서 마지막 실행 {when(brief.lastRun.startedAt)} · {brief.lastRun.status === "ok" ? `메시지 ${brief.lastRun.processed}개 → 후보 ${brief.lastRun.candidates}건` : brief.lastRun.status}
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
