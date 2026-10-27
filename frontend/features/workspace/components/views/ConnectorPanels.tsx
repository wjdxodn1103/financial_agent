"use client";

/**
 * 데이터 연결 — DART · SEC EDGAR · 한국은행 ECOS 를 탭으로. 가져온 것은 조회 시각이 찍힌 스냅샷 자료가 되어
 * 워크스페이스 자료·근거 원장에 들어간다. 키(또는 SEC 연락처)가 없는 연결은 안내만 한다.
 */
import { useEffect, useState } from "react";
import { Building2, LineChart, Loader2, PlugZap, Search, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "../../../report/api";
import { fetchEcosSeries, fetchEdgarFinancials, listConnectors, listEcosItems, searchEcosTables, searchEdgarCompanies } from "../../api";
import { useWorkspace } from "../../context";
import type { ConnectorInfo, EcosItem, EcosTable, EdgarCompany } from "../../types";
import { DartPanel } from "./DartPanel";

type Fetched = (docId: string) => void;

function Shell({ title, info, onClose, children }: { title: string; info: ConnectorInfo | null; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-primary-soft-border bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
          <PlugZap className="size-4 text-primary" aria-hidden />
          {title}
        </p>
        <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded p-1 text-text-secondary hover:bg-neutral-100">
          <X className="size-4" aria-hidden />
        </button>
      </div>
      {info && !info.ready ? <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">아직 연결되지 않았습니다. {info.hint}</p> : children}
    </div>
  );
}

const fail = (e: unknown, msg: string) => toast.error(e instanceof ApiError ? e.message : msg, { position: "top-center" });

function EdgarPanel({ info, onClose, onFetched }: { info: ConnectorInfo | null; onClose: () => void; onFetched: Fetched }) {
  const ws = useWorkspace();
  const [q, setQ] = useState("");
  const [list, setList] = useState<EdgarCompany[] | null>(null);
  const [picked, setPicked] = useState<EdgarCompany | null>(null);
  const [year, setYear] = useState(new Date().getFullYear() - 1);
  const [busy, setBusy] = useState<"search" | "fetch" | null>(null);

  const search = async () => {
    if (!q.trim() || busy) return;
    setBusy("search");
    try {
      const xs = await searchEdgarCompanies(ws.workspaceId, q.trim());
      setList(xs);
      setPicked(xs[0] ?? null);
    } catch (e) {
      fail(e, "회사를 찾지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };
  const fetchIt = async () => {
    if (!picked || busy) return;
    setBusy("fetch");
    try {
      const r = await fetchEdgarFinancials(ws.workspaceId, { cik: picked.cik, name: picked.name, year });
      toast.success(`${r.title} — 수치 ${r.figures}개를 원장에 넣었습니다.`, { position: "top-center" });
      if (r.document) onFetched(r.document.id);
    } catch (e) {
      fail(e, "가져오지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Shell title="SEC EDGAR 미국 상장사 재무" info={info} onClose={onClose}>
      <div className="mt-3 flex gap-2">
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-neutral-200 px-2.5 py-1.5">
          <Search className="size-4 text-text-secondary" aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void search()} placeholder="티커 또는 회사 이름(예: AAPL, Microsoft)" className="min-w-0 flex-1 text-sm outline-none" />
        </label>
        <Button size="sm" variant="outline" disabled={!q.trim() || busy !== null} onClick={() => void search()}>
          {busy === "search" ? <Loader2 className="animate-spin" aria-hidden /> : "찾기"}
        </Button>
      </div>
      {list && (
        <div className="thin-scrollbar mt-2 max-h-40 overflow-y-auto rounded-lg border border-neutral-200">
          {list.length === 0 && <p className="px-3 py-2 text-xs text-text-secondary">찾은 회사가 없습니다.</p>}
          {list.map((c) => (
            <button key={c.cik} type="button" onClick={() => setPicked(c)} className={cn("flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-neutral-50", picked?.cik === c.cik && "bg-primary-soft")}>
              <Building2 className="size-3.5 shrink-0 text-primary" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-text-primary">{c.name}</span>
              <span className="shrink-0 text-[11px] text-text-secondary">{c.ticker}</span>
            </button>
          ))}
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <label className="flex items-center gap-1 text-xs text-text-secondary">
          회계연도
          <input type="number" min={2009} max={new Date().getFullYear()} value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-20 rounded-md border border-neutral-200 px-2 py-1 text-sm text-text-primary" />
        </label>
        <Button size="sm" className="ml-auto" disabled={!picked || busy !== null} onClick={() => void fetchIt()}>
          {busy === "fetch" ? <Loader2 className="animate-spin" aria-hidden /> : null}
          {picked ? `${picked.ticker || picked.name} FY${year} 가져오기` : "회사를 고르세요"}
        </Button>
      </div>
      <p className="mt-2 text-[11px] text-text-secondary">연차 보고서(10-K 등)의 US GAAP 값을 3개 회계연도로 가져옵니다. 달러 원값 그대로 원장에 들어갑니다.</p>
    </Shell>
  );
}

const CYCLES = [
  { id: "A", label: "연" },
  { id: "Q", label: "분기" },
  { id: "M", label: "월" },
  { id: "D", label: "일" },
];

/** 주기별 기간 형식 — 끝에서 n 칸 앞 */
function backFrom(cycle: string, end: string, n: number): string {
  if (cycle === "A" && /^\d{4}$/.test(end)) return String(Number(end) - n + 1);
  if (cycle === "Q") {
    const m = /^(\d{4})Q([1-4])$/.exec(end);
    if (m) {
      const idx = Number(m[1]) * 4 + Number(m[2]) - 1 - (n - 1);
      return `${Math.floor(idx / 4)}Q${(idx % 4) + 1}`;
    }
  }
  if (cycle === "M" && /^\d{6}$/.test(end)) {
    const idx = Number(end.slice(0, 4)) * 12 + Number(end.slice(4)) - 1 - (n - 1);
    return `${Math.floor(idx / 12)}${String((idx % 12) + 1).padStart(2, "0")}`;
  }
  return end;
}

function EcosPanel({ info, onClose, onFetched }: { info: ConnectorInfo | null; onClose: () => void; onFetched: Fetched }) {
  const ws = useWorkspace();
  const [q, setQ] = useState("");
  const [tables, setTables] = useState<EcosTable[] | null>(null);
  const [table, setTable] = useState<EcosTable | null>(null);
  const [items, setItems] = useState<EcosItem[] | null>(null);
  const [item, setItem] = useState<EcosItem | null>(null);
  const [cycle, setCycle] = useState("M");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [busy, setBusy] = useState<"search" | "items" | "fetch" | null>(null);

  const search = async () => {
    if (!q.trim() || busy) return;
    setBusy("search");
    try {
      setTables(await searchEcosTables(ws.workspaceId, q.trim()));
      setTable(null);
      setItems(null);
      setItem(null);
    } catch (e) {
      fail(e, "통계표를 찾지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };
  const pickTable = async (t: EcosTable) => {
    setTable(t);
    setItem(null);
    setBusy("items");
    try {
      setItems(await listEcosItems(ws.workspaceId, t.statCode));
    } catch (e) {
      fail(e, "항목을 불러오지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };
  const pickItem = (it: EcosItem) => {
    setItem(it);
    const c = it.cycle || "M";
    setCycle(c);
    setEnd(it.end);
    setStart(backFrom(c, it.end, c === "M" ? 24 : c === "Q" ? 12 : c === "A" ? 10 : 60));
  };
  const fetchIt = async () => {
    if (!table || !item || busy) return;
    setBusy("fetch");
    try {
      const r = await fetchEcosSeries(ws.workspaceId, { statCode: table.statCode, statName: table.statName, itemCode: item.itemCode, itemName: item.itemName, cycle, start, end });
      toast.success(`${r.title} — 수치 ${r.figures}개를 원장에 넣었습니다.`, { position: "top-center" });
      if (r.document) onFetched(r.document.id);
    } catch (e) {
      fail(e, "가져오지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Shell title="한국은행 ECOS 경제 통계" info={info} onClose={onClose}>
      <div className="mt-3 flex gap-2">
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-neutral-200 px-2.5 py-1.5">
          <Search className="size-4 text-text-secondary" aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void search()} placeholder="통계표 이름(예: 기준금리, 환율, 소비자물가)" className="min-w-0 flex-1 text-sm outline-none" />
        </label>
        <Button size="sm" variant="outline" disabled={!q.trim() || busy !== null} onClick={() => void search()}>
          {busy === "search" ? <Loader2 className="animate-spin" aria-hidden /> : "찾기"}
        </Button>
      </div>
      {tables && (
        <div className="thin-scrollbar mt-2 max-h-32 overflow-y-auto rounded-lg border border-neutral-200">
          {tables.length === 0 && <p className="px-3 py-2 text-xs text-text-secondary">찾은 통계표가 없습니다.</p>}
          {tables.map((t) => (
            <button key={t.statCode} type="button" onClick={() => void pickTable(t)} className={cn("flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-neutral-50", table?.statCode === t.statCode && "bg-primary-soft")}>
              <LineChart className="size-3.5 shrink-0 text-primary" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-text-primary">{t.statName}</span>
              <span className="shrink-0 text-[11px] text-text-secondary">{t.statCode}</span>
            </button>
          ))}
        </div>
      )}
      {busy === "items" && <p className="mt-2 flex items-center gap-1 text-xs text-text-secondary"><Loader2 className="size-3 animate-spin" aria-hidden />항목 불러오는 중…</p>}
      {items && (
        <div className="thin-scrollbar mt-2 max-h-32 overflow-y-auto rounded-lg border border-neutral-200">
          {items.length === 0 && <p className="px-3 py-2 text-xs text-text-secondary">항목이 없습니다.</p>}
          {items.map((it, i) => (
            <button key={`${it.itemCode}-${it.cycle}-${i}`} type="button" onClick={() => pickItem(it)} className={cn("flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-neutral-50", item === it && "bg-primary-soft")}>
              <span className="min-w-0 flex-1 truncate text-text-primary">{it.itemName}</span>
              <span className="shrink-0 text-[11px] text-text-secondary">
                {CYCLES.find((c) => c.id === it.cycle)?.label ?? it.cycle} · {it.start}~{it.end} · {it.unit || "단위 없음"}
              </span>
            </button>
          ))}
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <select aria-label="주기" value={cycle} onChange={(e) => setCycle(e.target.value)} className="rounded-md border border-neutral-200 bg-white px-2 py-1 text-sm">
          {CYCLES.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
        <input aria-label="시작" value={start} onChange={(e) => setStart(e.target.value.trim())} placeholder="시작(202301)" className="w-24 rounded-md border border-neutral-200 px-2 py-1 text-sm" />
        <span className="text-text-secondary">~</span>
        <input aria-label="끝" value={end} onChange={(e) => setEnd(e.target.value.trim())} placeholder="끝(202412)" className="w-24 rounded-md border border-neutral-200 px-2 py-1 text-sm" />
        <Button size="sm" className="ml-auto" disabled={!item || !start || !end || busy !== null} onClick={() => void fetchIt()}>
          {busy === "fetch" ? <Loader2 className="animate-spin" aria-hidden /> : null}
          {item ? "가져오기" : "항목을 고르세요"}
        </Button>
      </div>
      <p className="mt-2 text-[11px] text-text-secondary">기간 형식: 연 2024 · 분기 2024Q1 · 월 202401 · 일 20240115. 최근 120개 시점까지 가져옵니다.</p>
    </Shell>
  );
}

export function ConnectorsPanel({ onClose, onFetched }: { onClose: () => void; onFetched: Fetched }) {
  const ws = useWorkspace();
  const [infos, setInfos] = useState<ConnectorInfo[]>([]);
  const [tab, setTab] = useState("dart");

  useEffect(() => {
    void listConnectors(ws.workspaceId)
      .then(setInfos)
      .catch(() => setInfos([]));
  }, [ws.workspaceId]);

  const info = (id: string) => infos.find((x) => x.id === id) ?? null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-1">
        {(infos.length ? infos : [{ id: "dart", title: "DART 전자공시", ready: false } as ConnectorInfo]).map((c) => (
          <button key={c.id} type="button" onClick={() => setTab(c.id)} className={cn("flex cursor-pointer items-center gap-1 rounded-full border px-2.5 py-1 text-xs", tab === c.id ? "border-primary-soft-border bg-primary-soft text-primary" : "border-neutral-200 text-text-secondary hover:bg-neutral-50")}>
            <span className={cn("size-1.5 rounded-full", c.ready ? "bg-emerald-500" : "bg-neutral-300")} aria-hidden />
            {c.title}
          </button>
        ))}
      </div>
      {tab === "edgar" ? <EdgarPanel info={info("edgar")} onClose={onClose} onFetched={onFetched} /> : tab === "ecos" ? <EcosPanel info={info("ecos")} onClose={onClose} onFetched={onFetched} /> : <DartPanel onClose={onClose} onFetched={onFetched} />}
    </div>
  );
}
