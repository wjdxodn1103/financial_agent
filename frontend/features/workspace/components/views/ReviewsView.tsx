"use client";

/**
 * 문서 검수 — 다른 사람이 쓴 문서의 숫자를 워크스페이스 근거 원장과 대조한다.
 * 왼쪽: 검수 목록·새 검수 / 가운데: 지적(불일치·계산 오류·근거 없음·문서 내부 불일치, 일치는 접어 둔다) → 작업 항목으로
 * 오른쪽: 대상 문서의 그 문장이나 근거 자료의 그 칸.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Calculator, CheckCircle2, ClipboardCheck, FileDown, HelpCircle, ListPlus, Loader2, SplitSquareHorizontal } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "../../../report/api";
import { DocViewerBody } from "../../../report/components/viewer/DocViewerBody";
import { downloadReviewMemo, getReview, listReviews, makeReviewTasks, startReview } from "../../api";
import { useWorkspace } from "../../context";
import { FEATURES } from "../../features";
import { useWorkspaceDocuments } from "../../hooks/useWorkspaceDocuments";
import type { Finding, FindingRule, Review } from "../../types";

const RULE: Record<FindingRule, { label: string; tone: string; icon: typeof AlertTriangle }> = {
  mismatch: { label: "불일치", tone: "bg-red-50 text-red-700 border-red-200", icon: AlertTriangle },
  calc: { label: "계산 오류", tone: "bg-orange-50 text-orange-700 border-orange-200", icon: Calculator },
  unsourced: { label: "근거 없음", tone: "bg-amber-50 text-amber-800 border-amber-200", icon: HelpCircle },
  internal: { label: "문서 내부 불일치", tone: "bg-violet-50 text-violet-700 border-violet-200", icon: SplitSquareHorizontal },
  ok: { label: "일치", tone: "bg-emerald-50 text-emerald-700 border-emerald-200", icon: CheckCircle2 },
};
const ORDER: FindingRule[] = ["mismatch", "calc", "unsourced", "internal"];

function Quote({ text, raw }: { text: string; raw: string }) {
  const i = raw ? text.indexOf(raw) : -1;
  if (i < 0) return <span>“{text}”</span>;
  return (
    <span>
      “{text.slice(0, i)}
      <mark className="rounded bg-yellow-200 px-0.5">{raw}</mark>
      {text.slice(i + raw.length)}”
    </span>
  );
}

export function ReviewsView() {
  const ws = useWorkspace();
  const docs = useWorkspaceDocuments(ws.workspaceId, false);
  const [reviews, setReviews] = useState<Review[] | null>(null);
  const [current, setCurrent] = useState<Review | null>(null);
  const [target, setTarget] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [assignee, setAssignee] = useState("");
  const [showOk, setShowOk] = useState(false);
  const [view, setView] = useState<{ docId: string; chunk: string; cell?: [number, number] | null; tick: number } | null>(null);
  const canReview = ws.can("reviewer");

  const refreshList = useCallback(async () => {
    try {
      setReviews(await listReviews(ws.workspaceId));
    } catch {
      setReviews([]);
    }
  }, [ws.workspaceId]);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  const open = useCallback(
    async (id: string) => {
      try {
        setCurrent(await getReview(ws.workspaceId, id));
        setPicked([]);
      } catch {
        toast.error("검수 결과를 불러오지 못했습니다.", { position: "top-center" });
      }
    },
    [ws.workspaceId],
  );

  // 도는 동안 2초마다
  useEffect(() => {
    if (current?.status !== "running") return;
    const t = setTimeout(() => {
      void open(current.id);
      void refreshList();
    }, 2000);
    return () => clearTimeout(t);
  }, [current, open, refreshList]);

  const start = async () => {
    if (!target) return;
    try {
      const r = await startReview(ws.workspaceId, target);
      setCurrent(r);
      void refreshList();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "검수를 시작하지 못했습니다.", { position: "top-center" });
    }
  };

  const toTasks = async () => {
    if (!current || !picked.length) return;
    try {
      const r = await makeReviewTasks(ws.workspaceId, current.id, picked, assignee || null);
      setCurrent(r);
      setPicked([]);
      toast.success(`할 일 ${r.made}건을 만들었습니다.`, { position: "top-center" });
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "할 일을 만들지 못했습니다.", { position: "top-center" });
    }
  };

  const [memoBusy, setMemoBusy] = useState(false);
  const memo = async () => {
    if (!current || memoBusy) return;
    setMemoBusy(true);
    try {
      await downloadReviewMemo(ws.workspaceId, current.id);
    } catch {
      toast.error("Word 파일을 만들지 못했습니다.", { position: "top-center" });
    } finally {
      setMemoBusy(false);
    }
  };

  const findings = useMemo(() => current?.findings ?? [], [current]);
  const issues = findings.filter((f) => f.rule !== "ok").sort((a, b) => ORDER.indexOf(a.rule) - ORDER.indexOf(b.rule));
  const oks = findings.filter((f) => f.rule === "ok");
  const summary = current?.summary && "counts" in current.summary ? current.summary : null;
  const viewDoc = view ? (docs.documents ?? []).find((d) => d.id === view.docId) : null;
  const members = ws.detail?.members ?? [];

  const card = (f: Finding) => {
    const r = RULE[f.rule];
    const Icon = r.icon;
    const checked = picked.includes(f.id);
    return (
      <div key={f.id} className={cn("rounded-xl border bg-white px-3.5 py-3", f.rule === "ok" ? "border-neutral-200" : "border-neutral-200 shadow-sm")}>
        <div className="flex items-start gap-2">
          {f.rule !== "ok" && canReview && !f.taskId && (
            <input type="checkbox" aria-label="할 일로 고르기" checked={checked} onChange={() => setPicked((p) => (checked ? p.filter((x) => x !== f.id) : [...p, f.id]))} className="mt-1" />
          )}
          <span className={cn("inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium", r.tone)}>
            <Icon className="size-3" aria-hidden />
            {r.label}
          </span>
          <span className="min-w-0 flex-1 text-sm font-medium text-text-primary">
            {f.claim.metric} {f.claim.period}
            {f.claim.basis ? ` · ${f.claim.basis}` : ""}
            <span className="ml-1.5 text-xs font-normal text-text-secondary">{f.claim.source === "table" ? "표" : "문장"}</span>
          </span>
          {f.taskId && <span className="shrink-0 rounded bg-primary-soft px-1.5 py-0.5 text-[10px] text-primary-soft-foreground">할 일 있음</span>}
        </div>
        <button
          type="button"
          onClick={() => current && setView((v) => ({ docId: current.docId, chunk: f.claim.chunk, cell: f.claim.cell ?? null, tick: (v?.tick ?? 0) + 1 }))}
          className="mt-1.5 block w-full cursor-pointer text-left text-xs leading-5 text-text-secondary hover:text-text-primary"
          title="대상 문서에서 보기"
        >
          <Quote text={f.claim.quote} raw={f.claim.raw} />
        </button>
        <p className="mt-1.5 text-sm text-text-primary">{f.message}</p>
        {f.formula && <p className="mt-1 rounded bg-background-gray px-2 py-1 font-mono text-[11px] text-text-secondary">계산식: {f.formula}</p>}
        {f.evidence.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {f.evidence.map((e) => (
              <button
                key={e.fid}
                type="button"
                onClick={() => setView((v) => ({ docId: e.docId, chunk: e.chunk, cell: e.cell, tick: (v?.tick ?? 0) + 1 }))}
                className={cn("cursor-pointer rounded-md border px-2 py-0.5 text-[11px] hover:bg-primary-soft", f.expected?.fid === e.fid ? "border-primary text-primary" : "border-neutral-200 text-text-secondary")}
              >
                {e.display} · {e.docLabel}
                {e.page ? ` p.${e.page}` : e.sheet ? ` ${e.sheet}` : ""}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="thin-scrollbar flex w-[280px] shrink-0 flex-col overflow-y-auto border-r border-neutral-200 bg-background-gray/50 px-3 py-5">
        <h1 className="px-1 text-[22px] leading-tight font-bold tracking-tight text-text-primary">문서 검수</h1>
        {canReview && (
          <div className="mt-4 rounded-xl border border-neutral-200 bg-white p-3">
            <label htmlFor="review-target" className="text-xs font-medium text-text-secondary">
              검수할 문서
            </label>
            <select id="review-target" value={target} onChange={(e) => setTarget(e.target.value)} className="mt-1 w-full rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-sm">
              <option value="">문서 고르기</option>
              {(docs.documents ?? []).filter((d) => !d.shared).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
            <Button size="sm" className="mt-2 w-full" disabled={!target} onClick={() => void start()}>
              <ClipboardCheck aria-hidden />
              검수 시작
            </Button>
          </div>
        )}
        <div className="mt-4 flex flex-col gap-1">
          {reviews === null && <p className="px-1 text-sm text-text-secondary">불러오는 중…</p>}
          {reviews?.length === 0 && <p className="px-1 text-sm text-text-secondary">아직 검수한 문서가 없습니다.</p>}
          {reviews?.map((r) => {
            const s = r.summary && "counts" in r.summary ? r.summary : null;
            const n = s ? s.counts.mismatch + s.counts.calc + s.counts.unsourced + s.counts.internal : 0;
            return (
              <button key={r.id} type="button" onClick={() => void open(r.id)} className={cn("cursor-pointer rounded-lg px-2.5 py-2 text-left hover:bg-white", current?.id === r.id && "bg-white shadow-sm")}>
                <span className="block truncate text-sm text-text-primary">{r.docLabel}</span>
                <span className="block text-[11px] text-text-secondary">
                  {r.status === "running" ? "검수 중…" : r.status === "error" ? "실패" : `지적 ${n}건`} · {ws.nameOf(r.createdBy)}
                </span>
              </button>
            );
          })}
        </div>
      </aside>

      <section className="thin-scrollbar min-w-0 flex-1 overflow-y-auto px-6 py-5">
        {!current ? (
          <div className="h-full" />
        ) : current.status === "running" ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-text-secondary">
            <Loader2 className="size-5 animate-spin" aria-hidden />
            &quot;{current.docLabel}&quot; 의 숫자를 뽑아 근거 원장과 대조하는 중
          </div>
        ) : current.status === "error" ? (
          <p className="text-sm text-red-600">검수에 실패했습니다: {current.error}</p>
        ) : (
          <>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-text-primary">{current.docLabel}</h2>
                {summary && (
                  <p className="mt-0.5 text-xs text-text-secondary">
                    숫자 주장 {summary.claims}개 · 근거 자료 {summary.referenceDocs ?? 0}건 · {summary.mode === "llm" ? `AI 추출 후보 ${summary.proposed}개 중 원문 확인 통과 ${(summary.proposed ?? 0) - (summary.rejected ?? 0)}개` : "규칙 추출"}
                    {summary.swept ? ` · 코드가 문장을 훑어 더 찾은 숫자 ${summary.swept}개` : ""}
                    {summary.unverifiable ? ` · 기간을 몰라 대조 못 함 ${summary.unverifiable}` : ""}
                  </p>
                )}
              </div>
              {summary && (
                <div className="flex flex-wrap items-center gap-1.5">
                  {[...ORDER, "ok" as FindingRule].map((k) => (
                    <span key={k} className={cn("rounded-full border px-2 py-0.5 text-[11px]", RULE[k].tone)}>
                      {RULE[k].label} {summary.counts[k] ?? 0}
                    </span>
                  ))}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={memoBusy}
                    onClick={() => void memo()}
                    title={current.fileName?.toLowerCase().endsWith(".docx") ? "원본 DOCX 에 지적을 Word 메모로 단 사본" : "지적 목록을 담은 검수 의견서 DOCX"}
                  >
                    {memoBusy ? <Loader2 className="animate-spin" aria-hidden /> : <FileDown aria-hidden />}
                    {current.fileName?.toLowerCase().endsWith(".docx") ? "Word 메모로 받기" : "검수 의견서 받기"}
                  </Button>
                </div>
              )}
            </div>

            {summary?.carry && (
              <div className="mt-4 rounded-xl border border-violet-200 bg-violet-50/60 px-4 py-3 text-sm text-violet-900">
                <p className="font-medium">
                  앞선 검수({summary.carry.previousLabel}) 대비 — 해소 {summary.carry.resolved.length} · 남음 {summary.carry.carried.length} · 새 지적 {summary.carry.new}
                  {FEATURES.tasks && summary.carry.autoDone > 0 && <span className="ml-1 text-xs font-normal">(할 일 {summary.carry.autoDone}건 자동 완료)</span>}
                </p>
                {summary.carry.resolved.length > 0 && (
                  <p className="mt-1 text-xs leading-5">
                    해소: {summary.carry.resolved.map((x) => `${RULE[x.rule]?.label ?? x.rule} ${x.metric} ${x.period}(${x.before})`).join(" · ")}
                  </p>
                )}
                {summary.carry.carried.length > 0 && (
                  <p className="text-xs leading-5">
                    남음: {summary.carry.carried.map((x) => `${RULE[x.rule]?.label ?? x.rule} ${x.metric} ${x.period}`).join(" · ")}
                  </p>
                )}
              </div>
            )}

            {FEATURES.tasks && issues.length > 0 && canReview && (
              <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-neutral-300 px-3 py-2">
                <ListPlus className="size-4 text-primary" aria-hidden />
                <span className="text-sm text-text-primary">고른 지적 {picked.length}건 → 할 일</span>
                <select aria-label="담당자" value={assignee} onChange={(e) => setAssignee(e.target.value)} className="rounded-md border border-neutral-200 bg-white px-2 py-1 text-sm">
                  <option value="">담당자 없음</option>
                  {members.map((m) => (
                    <option key={m.user.id} value={m.user.id}>
                      {m.user.name} {m.user.title}
                    </option>
                  ))}
                </select>
                <Button size="sm" disabled={!picked.length} onClick={() => void toTasks()}>
                  만들기
                </Button>
                <button type="button" className="ml-auto cursor-pointer text-xs text-primary hover:underline" onClick={() => setPicked(issues.filter((f) => !f.taskId).map((f) => f.id))}>
                  지적 모두 고르기
                </button>
              </div>
            )}

            <div className="mt-4 flex flex-col gap-2.5">
              {issues.length === 0 && <p className="rounded-xl border border-neutral-200 px-4 py-3 text-sm text-text-secondary">지적 없음</p>}
              {issues.map(card)}
            </div>
            {oks.length > 0 && (
              <div className="mt-5">
                <button type="button" onClick={() => setShowOk((v) => !v)} className="cursor-pointer text-xs text-text-secondary hover:text-text-primary">
                  {showOk ? "▾" : "▸"} 근거와 일치한 숫자 {oks.length}개
                </button>
                {showOk && <div className="mt-2 flex flex-col gap-2">{oks.map(card)}</div>}
              </div>
            )}
            {!!summary?.missed?.length && (
              <div className="mt-3 rounded-xl border border-neutral-200 bg-background-gray/60 px-3.5 py-2.5">
                <p className="text-xs font-medium text-text-primary">대조하지 못한 숫자 {summary.missed.length}개</p>
                <div className="mt-1.5 flex flex-col gap-1">
                  {summary.missed.map((m, i) => (
                    <button
                      key={`${m.chunk}-${i}`}
                      type="button"
                      onClick={() => current && setView((v) => ({ docId: current.docId, chunk: m.chunk, cell: null, tick: (v?.tick ?? 0) + 1 }))}
                      className="block w-full cursor-pointer text-left text-xs leading-5 text-text-secondary hover:text-text-primary"
                      title="대상 문서에서 보기"
                    >
                      <Quote text={m.quote} raw={m.raw} />
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </section>

      <aside className="flex w-[400px] shrink-0 flex-col border-l border-neutral-200">
        {view && viewDoc ? (
          <DocViewerBody workspaceId={ws.workspaceId} doc={viewDoc} focusChunk={view.chunk} focusCell={view.cell} tick={view.tick} />
        ) : null}
      </aside>
    </div>
  );
}
