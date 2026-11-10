"use client";

/**
 * 검토 제안 서랍 — 새 자료로 판단 기준에 걸린 문서의 제안. 메뉴 없이 문서 머리 '검토 제안'·섹션 끝 줄·홈·알림에서 연다.
 * 한 장 = 바뀐 것 · 설명 · 여유(한도까지) · 걸린 문장(원문 → 고친 문장) · 근거 셋(데이터 원문 · 기준 원문 · 과거 결정 원문).
 * 방향은 서버 코드가 기준으로 정한다 — 화면은 판정 색 없이 낱말만. [문서에 반영](작성자) · [재심의 안건 초안] · [닫기]. 결정은 위원회가 한다.
 */
import { useEffect, useRef, useState } from "react";
import { useAtom, useSetAtom } from "jotai";
import { Loader2, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import type { AnchorRef } from "../assumptions/api";
import { ApiError } from "../report/api";
import { focusStepAtom } from "../report/atoms";
import { SourceDialog, type SourceTarget } from "../report/components/viewer/SourceModal";
import { useWorkspace } from "../workspace/context";
import { applyProposal, dismissProposal, plainText, proposalAgenda, type ProposalView } from "./api";
import { proposalsDrawerAtom, REPORT_CHANGED, takePendingProposal, useDocProposals } from "./state";

const shortAt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "");

/** 워크스페이스 화면 어디서나 하나 — WorkspaceShell 에 둔다 */
export function ProposalsDrawerHost() {
  const [open, setOpen] = useAtom(proposalsDrawerAtom);
  useEffect(() => {
    const got = takePendingProposal();
    if (got) setOpen(got);
  }, [setOpen]);
  if (!open) return null;
  return <ProposalsDrawer key={open.reportId} {...open} onClose={() => setOpen(null)} />;
}

function ProposalsDrawer({ reportId, title, focusId, onClose }: { reportId: string; title: string; focusId?: string; onClose: () => void }) {
  const ws = useWorkspace();
  const { items, loaded, replace, reload } = useDocProposals(ws.workspaceId, reportId);
  const [source, setSource] = useState<SourceTarget | null>(null);
  const setFocusStep = useSetAtom(focusStepAtom);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && !source && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose, source]);

  /** 원문 — 올린 자료면 원문 창, AI 작업 문서면 그 문서(같은 문서면 그 섹션) */
  const openAnchor = (a?: AnchorRef | null) => {
    if (!a) return;
    if (a.kind === "report" && a.sessionId) {
      if (a.sessionId === reportId && a.step) {
        setFocusStep(a.step);
        onClose();
      } else ws.nav.openReport(a.sessionId);
      return;
    }
    if (a.docId && a.chunk) setSource({ docId: a.docId, chunk: a.chunk, cell: a.cell ?? null, tick: Date.now() });
  };

  const open = items.filter((p) => p.status === "open");
  const done = items.filter((p) => p.status !== "open");

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onMouseDown={onClose}>
      <aside onMouseDown={(e) => e.stopPropagation()} className="flex h-full w-full max-w-[520px] flex-col bg-white shadow-2xl">
        <header className="flex items-start gap-3 border-b border-neutral-200 px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-[17px] font-bold text-text-primary">검토 제안</h2>
            <p className="truncate text-[12px] text-text-secondary">{title}</p>
          </div>
          <button type="button" aria-label="닫기" onClick={onClose} className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-text-secondary hover:bg-neutral-100">
            <X className="size-4" aria-hidden />
          </button>
        </header>
        <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {!loaded && <p className="text-[13px] text-text-secondary">불러오는 중…</p>}
          {loaded && !items.length && <p className="text-[13px] text-text-secondary">이 문서에 검토 제안이 없습니다.</p>}
          {open.map((p) => (
            <Card key={p.id} p={p} focused={p.id === focusId} onChange={replace} onAnchor={openAnchor} onStep={(step) => (setFocusStep(step), onClose())} />
          ))}
          {done.length > 0 && <p className="mt-5 mb-1 text-[12px] font-semibold text-neutral-500">처리한 것 {done.length}</p>}
          {done.map((p) => (
            <Card key={p.id} p={p} focused={p.id === focusId} onChange={replace} onAnchor={openAnchor} onStep={(step) => (setFocusStep(step), onClose())} />
          ))}
        </div>
      </aside>
      {source && (
        <div onMouseDown={(e) => e.stopPropagation()}>
          <SourceDialog target={source} onClose={() => setSource(null)} />
        </div>
      )}
    </div>
  );
}

function Card({ p, focused, onChange, onAnchor, onStep }: { p: ProposalView; focused: boolean; onChange: (p: ProposalView) => void; onAnchor: (a?: AnchorRef | null) => void; onStep: (step: string) => void }) {
  const ws = useWorkspace();
  const ref = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const crit = p.criterion;
  const data = p.evidence.data ?? [];
  const decision = p.evidence.decision;
  const isOpen = p.status === "open";

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "center" });
  }, [focused]);

  const run = async (key: string, fn: () => Promise<ProposalView>, ok: string, fail: string) => {
    setBusy(key);
    try {
      const got = await fn();
      onChange(got);
      if (ok) toast.success(ok, { position: "top-center" });
      if (key === "apply") window.dispatchEvent(new CustomEvent(REPORT_CHANGED, { detail: { reportId: p.reportId } }));
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : fail, { position: "top-center" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div ref={ref} className={cn("mb-3 rounded-xl border border-neutral-200 px-4 py-3", focused && "bg-neutral-50", !isOpen && "opacity-80")}>
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 text-[14px] font-semibold text-text-primary">
          {p.directionKo} 검토 제안
          <span className="ml-1.5 font-normal text-text-secondary">
            · {crit.scope === "company" ? "사내" : "워크스페이스"} 기준 {crit.title} v{crit.version}
          </span>
        </p>
        {!isOpen && <span className="shrink-0 rounded-md bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-700">{p.statusKo}</span>}
      </div>
      <p className="mt-1 text-[13px] leading-5 text-text-primary">{p.changed}</p>
      {p.explanation && <p className="mt-1.5 text-[13px] leading-6 text-text-secondary">{p.explanation}</p>}
      {p.headroom.length > 0 && (
        <div className="mt-2 flex flex-col gap-0.5">
          {p.headroom.map((h) => (
            <p key={h.criterionId} className="text-[12px] text-text-primary tabular-nums">
              여유 · {h.display}
              {h.anchors[0] && (
                <button type="button" onClick={() => onAnchor(h.anchors[0])} className="ml-1.5 cursor-pointer text-text-secondary underline-offset-2 hover:underline">
                  보유 내역
                </button>
              )}
            </p>
          ))}
        </div>
      )}
      <div className="mt-2.5 flex flex-col gap-2">
        {p.sentences.map((s, i) => (
          <div key={i} className="rounded-lg bg-neutral-50 px-3 py-2 text-[12px] leading-5">
            <button type="button" onClick={() => onStep(s.step)} title="문서에서 이 문장 보기" className="cursor-pointer text-left text-text-secondary hover:text-text-primary">
              {plainText(s.plain || s.original)}
            </button>
            {s.revised ? (
              <p className="mt-1 text-text-primary">→ {plainText(s.revised)}</p>
            ) : (
              <p className="mt-1 text-text-secondary">→ 지금 값과 맞는지 확인할 문장</p>
            )}
            {s.why && <p className="mt-0.5 text-[11px] text-neutral-500">{s.why}</p>}
          </div>
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-1">
        {data.slice(0, 2).map((a, i) => (
          <Btn key={`d${i}`} onClick={() => onAnchor(a)} title={a.quote}>
            {i === 0 ? `데이터 원문${p.check.value.period ? ` ${p.check.value.period}` : ""}` : `비교 ${p.check.value.base || ""}`}
          </Btn>
        ))}
        {crit.anchor && (
          <Btn onClick={() => onAnchor(crit.anchor)} title={crit.quote}>
            기준 v{crit.version} 원문
          </Btn>
        )}
        {decision?.anchor && (
          <Btn onClick={() => onAnchor(decision.anchor)} title={decision.quote}>
            과거 결정 원문
          </Btn>
        )}
      </div>
      {(p.canAct || p.result.agendaId) && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-neutral-100 pt-2.5">
          {p.canApply && (
            <button
              type="button"
              disabled={!!busy}
              onClick={() => window.confirm("고친 문장을 문서에 넣습니다. 반영 전 판이 남습니다.") && void run("apply", () => applyProposal(p.id), "문서에 반영했습니다.", "반영하지 못했습니다.")}
              className="flex h-8 cursor-pointer items-center gap-1.5 rounded-lg bg-primary px-3 text-[12px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
            >
              {busy === "apply" && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
              문서에 반영
            </button>
          )}
          {p.result.agendaId ? (
            <Btn onClick={() => ws.nav.openReport(p.result.agendaId!)}>재심의 안건 열기</Btn>
          ) : (
            p.canAct &&
            ws.can("editor") && (
              <Btn
                disabled={!!busy || p.result.agendaStatus === "writing"}
                onClick={() => window.confirm("이 제안의 기준·지금 값·과거 결정으로 '재심의 안건' 초안을 씁니다. 다 쓰면 알림이 옵니다.") && void run("agenda", () => proposalAgenda(p.id), "재심의 안건을 쓰기 시작했습니다. 다 쓰면 알림이 옵니다.", "재심의 안건을 시작하지 못했습니다.")}
              >
                {p.result.agendaStatus === "writing" ? "안건 쓰는 중…" : p.result.agendaStatus === "error" ? "재심의 안건 다시" : "재심의 안건 초안"}
              </Btn>
            )
          )}
          {isOpen && ws.can("editor") && (
            <Btn disabled={!!busy} onClick={() => void run("dismiss", () => dismissProposal(p.id), "", "닫지 못했습니다.")}>
              닫기
            </Btn>
          )}
          <span className="ml-auto text-[11px] text-text-secondary">
            {shortAt(p.createdAt)}
            {p.check.asOf && ` · 기준일 ${p.check.asOf}`}
          </span>
        </div>
      )}
    </div>
  );
}

function Btn({ children, onClick, disabled, title }: { children: React.ReactNode; onClick: () => void; disabled?: boolean; title?: string }) {
  return (
    <button type="button" title={title} disabled={disabled} onClick={onClick} className="h-7 cursor-pointer rounded-md border border-neutral-200 px-2 text-[12px] text-text-primary hover:bg-neutral-50 disabled:cursor-default disabled:opacity-50">
      {children}
    </button>
  );
}
