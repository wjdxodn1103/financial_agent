"use client";

/** 소스 추가 — 종류 고르기 → 무엇을 모을지 → 언제 → 어디에(사내 공용은 관리자만). */
import { useEffect, useMemo, useState } from "react";
import { Check, Plus, Search, X } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ApiError } from "../report/api";
import { useWorkspace } from "../workspace/context";
import { createSource, getSourceCatalog, searchEdgarCompanies } from "./api";
import { KIND_ICON } from "./SourcesView";
import type { EdgarCompany, ScheduleEvery, SourceCatalog, SourceInfo, SourceKind } from "./types";

const KINDS: { id: SourceKind; label: string; desc: string }[] = [
  { id: "edgar", label: "공시", desc: "SEC EDGAR 새 공시·재무제표" },
  { id: "series", label: "시장·거시 시계열", desc: "금리·환율·원자재·지수" },
  { id: "rss", label: "공식 보도자료·성명", desc: "중앙은행·감독기관 피드" },
  { id: "folder", label: "수집 폴더", desc: "폴더에 넣은 파일 자동 적재" },
];
const EVERY: { id: ScheduleEvery; label: string }[] = [
  { id: "daily", label: "매일" },
  { id: "weekdays", label: "평일" },
  { id: "weekly", label: "매주" },
  { id: "hourly", label: "매시간" },
  { id: "manual", label: "손으로만" },
];

export function AddSourceDialog({ isAdmin, onClose, onCreated }: { isAdmin: boolean; onClose: () => void; onCreated: (s: SourceInfo) => void }) {
  const ws = useWorkspace();
  const [kind, setKind] = useState<SourceKind>("edgar");
  const [cat, setCat] = useState<SourceCatalog | null>(null);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"workspace" | "company">("workspace");
  const [every, setEvery] = useState<ScheduleEvery>("daily");
  const [time, setTime] = useState("06:30");
  const [weekday, setWeekday] = useState(0);
  const [series, setSeries] = useState<string[]>([]);
  const [feeds, setFeeds] = useState<{ url: string; issuer: string }[]>([]);
  const [feedUrl, setFeedUrl] = useState("");
  const [companies, setCompanies] = useState<EdgarCompany[]>([]);
  const [forms, setForms] = useState<string[]>(["10-Q", "10-K", "8-K"]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<EdgarCompany[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void getSourceCatalog().then((c) => {
      setCat(c);
      setSeries(c.series.filter((s) => !s.calc).map((s) => s.id));
      setFeeds(c.feeds);
    }, () => undefined);
  }, []);
  useEffect(() => {
    if (kind !== "edgar") return;
    const t = window.setTimeout(() => void searchEdgarCompanies(q).then(setHits, () => setHits([])), 200);
    return () => window.clearTimeout(t);
  }, [q, kind]);

  const groups = useMemo(() => {
    const out = new Map<string, SourceCatalog["series"]>();
    for (const s of cat?.series ?? []) if (!s.calc) out.set(s.group, [...(out.get(s.group) ?? []), s]);
    return [...out.entries()];
  }, [cat]);

  const submit = async () => {
    const params =
      kind === "series" ? { seriesIds: series } : kind === "rss" ? { feeds } : kind === "edgar" ? { companies: companies.map(({ cik, ticker, name: n }) => ({ cik, ticker, name: n })), forms } : {};
    if (kind === "edgar" && !companies.length) return toast.error("모을 회사를 하나 이상 고르세요.", { position: "top-center" });
    if (kind === "rss" && !feeds.length) return toast.error("피드를 하나 이상 넣으세요.", { position: "top-center" });
    setBusy(true);
    try {
      const s = await createSource(ws.workspaceId, {
        kind,
        scope,
        name: name.trim() || KINDS.find((k) => k.id === kind)!.label,
        params,
        schedule: { every, times: every === "hourly" || every === "manual" ? [] : [time], ...(every === "weekly" ? { weekday } : {}) },
      });
      onCreated(s);
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "등록하지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  const chip = (on: boolean) => cn("cursor-pointer rounded-lg px-2.5 py-1 text-[12px] font-medium", on ? "bg-primary-soft text-primary" : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="flex max-h-[88vh] w-full max-w-[640px] flex-col overflow-hidden rounded-[24px] bg-white shadow-xl">
        <div className="flex items-center justify-between px-6 pt-5 pb-3">
          <h2 className="text-[19px] font-bold text-text-primary">소스 추가</h2>
          <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-6 pb-4">
          <div className="grid grid-cols-2 gap-2">
            {KINDS.map((k) => {
              const Icon = KIND_ICON[k.id];
              return (
                <button key={k.id} type="button" onClick={() => setKind(k.id)} className={cn("flex cursor-pointer items-start gap-2.5 rounded-2xl px-3.5 py-3 text-left", kind === k.id ? "bg-primary-soft ring-2 ring-primary/40" : "bg-neutral-100 hover:bg-neutral-200")}>
                  <Icon className="mt-0.5 size-[18px] shrink-0 text-primary" aria-hidden />
                  <span>
                    <span className="block text-[14px] font-semibold text-text-primary">{k.label}</span>
                    <span className="block text-[12px] text-text-secondary">{k.desc}</span>
                  </span>
                </button>
              );
            })}
          </div>

          <label className="mt-4 block text-[13px] font-semibold text-text-secondary">이름</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={KINDS.find((k) => k.id === kind)!.label} className="mt-1 h-10 w-full rounded-xl bg-neutral-100 px-3 text-[14px] outline-none focus:ring-2 focus:ring-primary/30" />

          {kind === "edgar" && (
            <div className="mt-4">
              <label className="block text-[13px] font-semibold text-text-secondary">회사</label>
              {cat?.edgarMode === "fixture" && <p className="mt-0.5 text-[12px] text-amber-700">SEC_USER_AGENT 가 없어 고정 파일(가상) 회사만 고를 수 있습니다.</p>}
              <div className="mt-1 flex items-center gap-2 rounded-xl bg-neutral-100 px-3">
                <Search className="size-4 text-neutral-500" aria-hidden />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="회사 이름·티커" className="h-10 min-w-0 flex-1 bg-transparent text-[14px] outline-none" />
              </div>
              <div className="mt-1 flex max-h-[140px] flex-col overflow-y-auto">
                {hits.map((h) => {
                  const on = companies.some((c) => c.cik === h.cik);
                  return (
                    <button key={h.cik} type="button" onClick={() => setCompanies((cs) => (on ? cs.filter((c) => c.cik !== h.cik) : [...cs, h]))} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] hover:bg-neutral-50">
                      <span className={cn("flex size-4 items-center justify-center rounded border", on ? "border-primary bg-primary text-white" : "border-neutral-300")}>{on && <Check className="size-3" aria-hidden />}</span>
                      <span className="font-medium text-text-primary">{h.name}</span>
                      <span className="text-text-secondary">{h.ticker}</span>
                    </button>
                  );
                })}
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(cat?.forms ?? []).map((f) => (
                  <button key={f} type="button" onClick={() => setForms((fs) => (fs.includes(f) ? fs.filter((x) => x !== f) : [...fs, f]))} className={chip(forms.includes(f))}>
                    {f}
                  </button>
                ))}
              </div>
            </div>
          )}

          {kind === "series" && (
            <div className="mt-4 flex flex-col gap-2">
              {groups.map(([g, list]) => (
                <div key={g}>
                  <p className="mb-1 text-[12px] font-semibold text-text-secondary">{g}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {list.map((s) => (
                      <button key={s.id} type="button" onClick={() => setSeries((xs) => (xs.includes(s.id) ? xs.filter((x) => x !== s.id) : [...xs, s.id]))} className={chip(series.includes(s.id))}>
                        {s.name}
                        {s.virtual && <span className="ml-1 text-amber-700">가상</span>}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {kind === "rss" && (
            <div className="mt-4">
              <label className="block text-[13px] font-semibold text-text-secondary">피드</label>
              <div className="mt-1 flex flex-col gap-1">
                {feeds.map((f) => (
                  <div key={f.url} className="flex items-center gap-2 rounded-lg bg-neutral-50 px-2.5 py-1.5 text-[12px]">
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-medium text-text-primary">{f.issuer || "피드"}</span> <span className="text-text-secondary">{f.url}</span>
                    </span>
                    <button type="button" aria-label="빼기" onClick={() => setFeeds((fs) => fs.filter((x) => x.url !== f.url))} className="cursor-pointer text-neutral-400 hover:text-neutral-700">
                      <X className="size-3.5" aria-hidden />
                    </button>
                  </div>
                ))}
              </div>
              <div className="mt-1.5 flex gap-2">
                <input value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} placeholder="https://… (RSS 주소)" className="h-9 min-w-0 flex-1 rounded-xl bg-neutral-100 px-3 text-[13px] outline-none" />
                <button
                  type="button"
                  disabled={!/^https?:\/\//.test(feedUrl.trim())}
                  onClick={() => {
                    setFeeds((fs) => [...fs, { url: feedUrl.trim(), issuer: "" }]);
                    setFeedUrl("");
                  }}
                  className="flex h-9 cursor-pointer items-center gap-1 rounded-xl bg-neutral-100 px-3 text-[12px] font-semibold text-neutral-700 hover:bg-neutral-200 disabled:opacity-40"
                >
                  <Plus className="size-3.5" aria-hidden />
                  넣기
                </button>
              </div>
            </div>
          )}

          {kind === "folder" && <p className="mt-4 rounded-xl bg-neutral-50 px-3 py-2.5 text-[13px] text-text-secondary">등록하면 서버에 수집 폴더가 생깁니다. 그 폴더에 넣은 파일은 예약 때마다 적재·분류됩니다.</p>}

          <label className="mt-4 block text-[13px] font-semibold text-text-secondary">언제</label>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {EVERY.map((e) => (
              <button key={e.id} type="button" onClick={() => setEvery(e.id)} className={chip(every === e.id)}>
                {e.label}
              </button>
            ))}
            {every === "weekly" && (
              <select value={weekday} onChange={(e) => setWeekday(Number(e.target.value))} className="h-8 rounded-lg bg-neutral-100 px-2 text-[12px]">
                {["월", "화", "수", "목", "금", "토", "일"].map((d, i) => (
                  <option key={d} value={i}>
                    {d}요일
                  </option>
                ))}
              </select>
            )}
            {every !== "hourly" && every !== "manual" && <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="h-8 rounded-lg bg-neutral-100 px-2 text-[12px]" />}
          </div>

          <label className="mt-4 block text-[13px] font-semibold text-text-secondary">어디에 쌓을까요</label>
          <div className="mt-1 flex gap-1.5">
            <button type="button" onClick={() => setScope("workspace")} className={chip(scope === "workspace")}>
              이 워크스페이스
            </button>
            <button type="button" disabled={!isAdmin} onClick={() => setScope("company")} className={cn(chip(scope === "company"), !isAdmin && "cursor-not-allowed opacity-40")}>
              사내 공용{!isAdmin && "(관리자)"}
            </button>
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-neutral-100 px-6 py-4">
          <button type="button" onClick={onClose} className="h-10 cursor-pointer rounded-xl px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-100">
            닫기
          </button>
          <button type="button" disabled={busy} onClick={() => void submit()} className="h-10 cursor-pointer rounded-xl bg-primary px-5 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
            등록
          </button>
        </div>
      </div>
    </div>
  );
}
