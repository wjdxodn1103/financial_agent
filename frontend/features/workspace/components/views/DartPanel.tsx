"use client";

/**
 * 데이터 연결 — DART 재무제표·정기보고서 본문 가져오기. 회사 찾기 → 연도·보고서·(재무제표면 연결/별도) → 가져오기.
 * 가져온 것은 조회 시각이 찍힌 스냅샷 자료가 되어 워크스페이스 자료·근거 원장에 들어간다.
 */
import { useEffect, useState } from "react";
import { Building2, Loader2, PlugZap, Search, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "../../../report/api";
import { fetchDartBusiness, fetchDartFinancials, listConnectors, searchDartCompanies } from "../../api";
import { useWorkspace } from "../../context";
import type { ConnectorInfo, DartCompany } from "../../types";

const REPORTS = [
  { id: "annual", label: "사업보고서" },
  { id: "half", label: "반기" },
  { id: "q1", label: "1분기" },
  { id: "q3", label: "3분기" },
];

export function DartPanel({ onClose, onFetched }: { onClose: () => void; onFetched: (docId: string) => void }) {
  const ws = useWorkspace();
  const [info, setInfo] = useState<ConnectorInfo | null>(null);
  const [q, setQ] = useState("");
  const [companies, setCompanies] = useState<DartCompany[] | null>(null);
  const [picked, setPicked] = useState<DartCompany | null>(null);
  const [year, setYear] = useState(new Date().getFullYear() - 1);
  const [report, setReport] = useState("annual");
  const [fs, setFs] = useState("CFS");
  const [kind, setKind] = useState<"fs" | "body">("fs");
  const [busy, setBusy] = useState<"search" | "fetch" | null>(null);

  useEffect(() => {
    void listConnectors(ws.workspaceId)
      .then((xs) => setInfo(xs.find((x) => x.id === "dart") ?? null))
      .catch(() => setInfo(null));
  }, [ws.workspaceId]);

  const search = async () => {
    if (!q.trim() || busy) return;
    setBusy("search");
    try {
      const xs = await searchDartCompanies(ws.workspaceId, q.trim());
      setCompanies(xs);
      setPicked(xs.find((x) => x.listed) ?? xs[0] ?? null);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "회사를 찾지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(null);
    }
  };

  const fetchIt = async () => {
    if (!picked || busy) return;
    setBusy("fetch");
    try {
      if (kind === "body") {
        const r = await fetchDartBusiness(ws.workspaceId, { corpCode: picked.corpCode, corpName: picked.corpName, year, report });
        toast.success(`${r.title} — 문단·표 ${r.paragraphs}개를 가져왔습니다.`, { position: "top-center" });
        if (r.document) onFetched(r.document.id);
      } else {
        const r = await fetchDartFinancials(ws.workspaceId, { corpCode: picked.corpCode, corpName: picked.corpName, year, report, fs });
        toast.success(`${r.title} — 수치 ${r.figures}개를 원장에 넣었습니다.`, { position: "top-center" });
        if (r.document) onFetched(r.document.id);
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "가져오지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="rounded-xl border border-primary-soft-border bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
          <PlugZap className="size-4 text-primary" aria-hidden />
          DART 전자공시
        </p>
        <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded p-1 text-text-secondary hover:bg-neutral-100">
          <X className="size-4" aria-hidden />
        </button>
      </div>
      {info && !info.ready ? (
        <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">아직 연결되지 않았습니다. {info.hint}</p>
      ) : (
        <>
          <div className="mt-3 flex gap-2">
            <label className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-neutral-200 px-2.5 py-1.5">
              <Search className="size-4 text-text-secondary" aria-hidden />
              <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void search()} placeholder="회사 이름(예: 삼성전자)" className="min-w-0 flex-1 text-sm outline-none" />
            </label>
            <Button size="sm" variant="outline" disabled={!q.trim() || busy !== null} onClick={() => void search()}>
              {busy === "search" ? <Loader2 className="animate-spin" aria-hidden /> : "찾기"}
            </Button>
          </div>
          {companies && (
            <div className="thin-scrollbar mt-2 max-h-40 overflow-y-auto rounded-lg border border-neutral-200">
              {companies.length === 0 && <p className="px-3 py-2 text-xs text-text-secondary">찾은 회사가 없습니다.</p>}
              {companies.map((c) => (
                <button
                  key={c.corpCode}
                  type="button"
                  onClick={() => setPicked(c)}
                  className={cn("flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-neutral-50", picked?.corpCode === c.corpCode && "bg-primary-soft")}
                >
                  <Building2 className="size-3.5 shrink-0 text-primary" aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-text-primary">{c.corpName}</span>
                  <span className="shrink-0 text-[11px] text-text-secondary">{c.listed ? `상장 ${c.stockCode}` : "비상장"}</span>
                </button>
              ))}
            </div>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <label className="flex items-center gap-1 text-xs text-text-secondary">
              사업연도
              <input type="number" min={2015} max={new Date().getFullYear()} value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-20 rounded-md border border-neutral-200 px-2 py-1 text-sm text-text-primary" />
            </label>
            <select aria-label="보고서" value={report} onChange={(e) => setReport(e.target.value)} className="rounded-md border border-neutral-200 bg-white px-2 py-1 text-sm">
              {REPORTS.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
            <select aria-label="가져올 것" value={kind} onChange={(e) => setKind(e.target.value as "fs" | "body")} className="rounded-md border border-neutral-200 bg-white px-2 py-1 text-sm">
              <option value="fs">재무제표</option>
              <option value="body">본문(사업의 내용·주주)</option>
            </select>
            {kind === "fs" && (
              <select aria-label="연결 또는 별도" value={fs} onChange={(e) => setFs(e.target.value)} className="rounded-md border border-neutral-200 bg-white px-2 py-1 text-sm">
                <option value="CFS">연결</option>
                <option value="OFS">별도</option>
              </select>
            )}
            <Button size="sm" className="ml-auto" disabled={!picked || busy !== null} onClick={() => void fetchIt()}>
              {busy === "fetch" ? <Loader2 className="animate-spin" aria-hidden /> : null}
              {picked ? `${picked.corpName} 가져오기` : "회사를 고르세요"}
            </Button>
          </div>
          <p className="mt-2 text-[11px] text-text-secondary">가져온 것은 조회 시각이 찍힌 스냅샷 자료로 저장됩니다. 재무제표는 원 단위 값 그대로 근거 원장에, 본문은 원문 문단·표 그대로 들어갑니다.</p>
        </>
      )}
    </div>
  );
}
