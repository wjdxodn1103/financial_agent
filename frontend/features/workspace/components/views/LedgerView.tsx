"use client";

/**
 * 근거 원장 — 자료의 표 칸에서 뽑은 수치를 (지표·기간·기준)으로 묶어 보여 준다.
 * 같은 묶음에 값이 여럿이면 충돌 — 값을 채택하면 결정 기록으로 남는다(편집자 이상).
 * 수치를 누르면 오른쪽에 원문 표가 열리고 그 칸이 강조된다.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, FileSpreadsheet, Loader2, Search } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "../../../report/api";
import { AdoptReason } from "../../../report/components/report/AdoptReason";
import { DocViewerBody } from "../../../report/components/viewer/DocViewerBody";
import { chooseLedgerValue, downloadLedgerXlsx, getLedger } from "../../api";
import { useWorkspace } from "../../context";
import { useWorkspaceDocuments } from "../../hooks/useWorkspaceDocuments";
import type { Figure, Ledger, LedgerGroup } from "../../types";

/** 원 단위 큰 금액은 읽기 쉬운 단위를 덧붙인다(값 자체는 원문 그대로) */
function approx(abs: number, unit: string, percent: boolean): string {
  if (percent || Math.abs(abs) < 1e8 || !/원/.test(unit)) return "";
  const [s, w] = Math.abs(abs) >= 1e12 ? [1e12, "조원"] : [1e8, "억원"];
  return `약 ${(abs / s).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}${w}`;
}

function where(f: Figure): string {
  const loc = f.page ? `p.${f.page}` : f.sheet ? `시트 ${f.sheet}` : `문단 ${f.chunk}`;
  return f.cell ? `${loc} · ${f.cell[0] + 1}행 ${f.cell[1] + 1}열` : loc;
}

export function LedgerView() {
  const ws = useWorkspace();
  const docs = useWorkspaceDocuments(ws.workspaceId, false);
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [query, setQuery] = useState("");
  const [onlyConflicts, setOnlyConflicts] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ figure: Figure; tick: number } | null>(null);
  const [exporting, setExporting] = useState(false);
  const [asking, setAsking] = useState<string | null>(null);
  const [choosing, setChoosing] = useState(false);
  const canChoose = ws.can("editor");

  const load = useCallback(async () => {
    try {
      setLedger(await getLedger(ws.workspaceId));
    } catch {
      toast.error("원장을 불러오지 못했습니다.", { position: "top-center" });
    }
  }, [ws.workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const byId = useMemo(() => new Map((ledger?.figures ?? []).map((f) => [f.fid, f])), [ledger]);
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (ledger?.groups ?? []).filter((g) => (!onlyConflicts || (g.conflict && !g.chosen)) && (!q || `${g.metric} ${g.period} ${g.basis ?? ""}`.toLowerCase().includes(q)));
  }, [ledger, onlyConflicts, query]);

  const choose = async (g: LedgerGroup, figureId: string, reason: string) => {
    setChoosing(true);
    try {
      setLedger(await chooseLedgerValue(ws.workspaceId, g.key, figureId, reason));
      setAsking(null);
      toast.success("채택했습니다. 결정 기록에 남겼습니다.", { position: "top-center" });
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "채택하지 못했습니다.", { position: "top-center" });
    } finally {
      setChoosing(false);
    }
  };

  const exportXlsx = async () => {
    setExporting(true);
    try {
      await downloadLedgerXlsx(ws.workspaceId);
    } catch {
      toast.error("엑셀로 내보내지 못했습니다.", { position: "top-center" });
    } finally {
      setExporting(false);
    }
  };

  const focusDoc = focus ? (docs.documents ?? []).find((d) => d.id === focus.figure.doc) : null;
  const stats = ledger?.stats;

  return (
    <div className="flex min-h-0 flex-1">
      <section className="thin-scrollbar flex min-w-0 flex-1 flex-col overflow-y-auto px-8 py-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[26px] leading-tight font-bold tracking-tight text-text-primary">근거 원장</h1>
            <p className="mt-1 text-sm text-text-secondary">자료의 표 칸에서 코드가 뽑은 수치입니다. 같은 지표·기간에 값이 다르면 충돌로 표시합니다.</p>
          </div>
          {stats && (
            <div className="flex items-center gap-3">
              <p className="flex items-center gap-3 text-xs text-text-secondary tabular-nums">
                <span>수치 {stats.figures}</span>
                <span>묶음 {stats.groups}</span>
                <span className={cn(stats.conflicts && "font-semibold text-amber-700")}>미해결 충돌 {stats.conflicts}</span>
                <span>채택 {stats.resolved}</span>
              </p>
              <Button size="sm" variant="outline" disabled={exporting || !stats.figures} onClick={() => void exportXlsx()} title="원장·충돌·채택·계산 시트 — 계산 결과는 원장 칸을 참조하는 엑셀 수식">
                {exporting ? <Loader2 className="animate-spin" aria-hidden /> : <FileSpreadsheet aria-hidden />}
                엑셀로 내보내기
              </Button>
            </div>
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <label className="flex min-w-[240px] flex-1 items-center gap-2 rounded-lg border border-neutral-200 px-3 py-1.5">
            <Search className="size-4 text-text-secondary" aria-hidden />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="지표·기간으로 찾기 (예: 매출액 2024)" className="min-w-0 flex-1 text-sm outline-none" />
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-text-secondary">
            <input type="checkbox" checked={onlyConflicts} onChange={(e) => setOnlyConflicts(e.target.checked)} />
            미해결 충돌만
          </label>
        </div>

        <div className="mt-4 overflow-hidden rounded-xl border border-neutral-200">
          <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,0.8fr)_minmax(0,0.6fr)_minmax(0,1.4fr)_7.5rem] gap-2 border-b border-neutral-200 bg-background-gray px-4 py-2 text-[11px] font-semibold text-text-secondary">
            <span>지표</span>
            <span>기간</span>
            <span>기준</span>
            <span>값</span>
            <span className="text-right">상태</span>
          </div>
          {ledger === null && <p className="px-4 py-6 text-sm text-text-secondary">불러오는 중…</p>}
          {ledger && groups.length === 0 && <p className="px-4 py-6 text-sm text-text-secondary">{ledger.groups.length ? "조건에 맞는 수치가 없습니다." : "아직 수치가 없습니다. 표가 든 자료(PDF·DOCX·XLSX)를 올리면 자동으로 채워집니다."}</p>}
          {groups.map((g) => {
            const expanded = open === g.key;
            const unresolved = g.conflict && !g.chosen;
            return (
              <div key={g.key} className="border-b border-neutral-100 last:border-b-0">
                <button
                  type="button"
                  onClick={() => setOpen(expanded ? null : g.key)}
                  aria-expanded={expanded}
                  className={cn("grid w-full cursor-pointer grid-cols-[minmax(0,1.6fr)_minmax(0,0.8fr)_minmax(0,0.6fr)_minmax(0,1.4fr)_7.5rem] items-center gap-2 px-4 py-2 text-left text-sm hover:bg-neutral-50", unresolved && "bg-amber-50/60")}
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    {expanded ? <ChevronDown className="size-3.5 shrink-0 text-text-secondary" aria-hidden /> : <ChevronRight className="size-3.5 shrink-0 text-text-secondary" aria-hidden />}
                    <span className="truncate text-text-primary">{g.metric}</span>
                  </span>
                  <span className="truncate text-text-secondary">{g.period}</span>
                  <span className="truncate text-text-secondary">{g.basis ?? "—"}</span>
                  <span className="truncate font-medium text-text-primary tabular-nums">
                    {g.value ? g.value.display : g.values.map((v) => v.display).join(" / ")}
                    {g.value && approx(g.value.abs, g.value.unit, false) && <span className="ml-1 text-[11px] font-normal text-text-secondary">({approx(g.value.abs, g.value.unit, false)})</span>}
                    {g.unitUnknown && <span className="ml-1 text-[10px] font-normal text-amber-700">단위 불명 포함</span>}
                  </span>
                  <span className="flex justify-end">
                    {unresolved ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-800">
                        <AlertTriangle className="size-3" aria-hidden />
                        충돌
                      </span>
                    ) : g.chosen ? (
                      <span className="rounded-full bg-primary-soft px-2 py-0.5 text-[11px] text-primary-soft-foreground">채택됨</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[11px] text-emerald-700">
                        <CheckCircle2 className="size-3" aria-hidden />
                        {g.documents > 1 ? `${g.documents}곳 일치` : "1곳"}
                      </span>
                    )}
                  </span>
                </button>
                {expanded && (
                  <div className="flex flex-col gap-1 bg-background-gray/60 px-4 pt-1 pb-3 pl-9">
                    {g.figureIds.map((id) => {
                      const f = byId.get(id);
                      if (!f) return null;
                      const isChosen = g.chosen?.figureId === id;
                      return (
                        <div key={id} className={cn("flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border bg-white px-3 py-1.5 text-xs", isChosen ? "border-primary" : "border-neutral-200", focus?.figure.fid === id && "ring-2 ring-yellow-300")}>
                          <span className="w-28 shrink-0 font-medium text-text-primary tabular-nums">{f.display}</span>
                          <button type="button" onClick={() => setFocus((cur) => ({ figure: f, tick: (cur?.tick ?? 0) + 1 }))} className="min-w-0 flex-1 cursor-pointer truncate text-left text-primary hover:underline" title="원문 표 보기">
                            {f.docLabel} · {where(f)}
                            {f.source === "dart" && <span className="ml-1 rounded bg-sky-50 px-1 text-[10px] text-sky-700">DART</span>}
                          </button>
                          <span className="shrink-0 text-text-secondary">원문 &quot;{f.raw}&quot;</span>
                          {g.conflict && canChoose && !isChosen && asking !== id && (
                            <button type="button" onClick={() => setAsking(id)} className="shrink-0 cursor-pointer rounded-md border border-primary px-2 py-0.5 text-[11px] font-medium text-primary hover:bg-primary-soft">
                              이 값 채택
                            </button>
                          )}
                          {isChosen && <span className="shrink-0 rounded-md bg-primary px-2 py-0.5 text-[11px] text-white">채택</span>}
                          {asking === id && <AdoptReason display={f.display} busy={choosing} onSubmit={(reason) => void choose(g, id, reason)} onCancel={() => setAsking(null)} />}
                        </div>
                      );
                    })}
                    {g.chosen && (
                      <p className="mt-1 text-[11px] text-text-secondary">
                        {ws.nameOf(g.chosen.chosenBy)} 채택{g.chosen.reason ? ` — 사유: ${g.chosen.reason}` : ""}
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <aside className="flex w-[420px] shrink-0 flex-col border-l border-neutral-200">
        {focus && focusDoc ? (
          <DocViewerBody workspaceId={ws.workspaceId} doc={focusDoc} focusChunk={focus.figure.chunk} focusCell={focus.figure.cell} tick={focus.tick} />
        ) : (
          <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-text-secondary">묶음을 펼쳐 출처를 누르면 원문 표가 열리고 그 칸이 강조됩니다.</div>
        )}
      </aside>
    </div>
  );
}
