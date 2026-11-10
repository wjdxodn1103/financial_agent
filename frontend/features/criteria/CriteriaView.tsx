"use client";

/**
 * 문서 검수 ▸ 판단 기준 — KIC 투자 노하우를 '조건 → 방향' 항목으로. 사내 공통(관리자 승인) · 이 워크스페이스(소유자 승인).
 * 승인된(사용 중) 기준만 AI 가 쓴다 — 대화·작성기 브리프에 관련 기준을 싣고, 새 자료로 조건에 도달하면 걸린 문서에 검토 제안을 낸다.
 * 기준마다 원문 인용(출처 문서)·판·승인자. 승인 대기 = 자료에서 뽑은 초안 + 승인된 보고서에서 나온 수정안(바뀐 것·충돌 나란히).
 */
import { useEffect, useMemo, useState } from "react";
import { ChevronRight, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import type { AnchorRef } from "../assumptions/api";
import { ApiError, getDocuments } from "../report/api";
import type { DocumentCard, SessionListItem } from "../report/types";
import { listReports } from "../workspace/api";
import { useWorkspace } from "../workspace/context";
import { PageHeader } from "../workspace/components/views/PageHeader";
import { useOpenSource } from "../workspace/sourceHost";
import { criterionVersions, decideCriterion, extractCriteria, listCriteria, patchCriterion, scanCriteria, type CriteriaPayload, type CriterionView } from "./api";

type Scope = "all" | "company" | "workspace";
type Tab = "active" | "draft" | "archived";
const DIRECTIONS: [string, string][] = [["review", "재심의"], ["reduce", "축소 검토"], ["expand", "확대 검토"], ["hold", "유지"]];
const OPS: [string, string][] = [[">=", "이상"], [">", "초과"], ["<=", "이하"], ["<", "미만"]];
const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString("ko-KR", { year: "numeric", month: "numeric", day: "numeric" }) : "");
const show = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));

export function CriteriaView({ initial }: { initial?: string | null }) {
  const ws = useWorkspace();
  const [data, setData] = useState<CriteriaPayload | null>(null);
  const [scope, setScope] = useState<Scope>("all");
  const [tab, setTab] = useState<Tab>("active");
  const [picking, setPicking] = useState(false);
  const [asOf, setAsOf] = useState("");
  const [scanning, setScanning] = useState(false);

  const load = async () => {
    try {
      setData(await listCriteria(ws.workspaceId));
    } catch {
      setData({ criteria: [], canApprove: { company: false, workspace: false }, canExtract: { company: false, workspace: false } });
    }
  };
  useEffect(() => {
    void load();
  }, [ws.workspaceId]); // eslint-disable-line react-hooks/exhaustive-deps

  // 알림에서 연 기준 — 그 기준이 있는 탭으로
  useEffect(() => {
    const c = initial && data?.criteria.find((x) => x.id === initial);
    if (c) setTab(c.status === "draft" ? "draft" : c.status === "active" ? "active" : "archived");
  }, [initial, data]);

  const rows = useMemo(() => (data?.criteria ?? []).filter((c) => scope === "all" || c.scope === scope), [data, scope]);
  const count = (t: Tab) => rows.filter((c) => (t === "archived" ? c.status === "archived" : c.status === t)).length;
  const shown = rows.filter((c) => (tab === "archived" ? c.status === "archived" : c.status === tab));
  const replace = (c: CriterionView) => void load().then(() => c.status === "active" && setTab("active"));

  const scan = async () => {
    setScanning(true);
    try {
      const r = await scanCriteria(ws.workspaceId, asOf || null);
      toast.success(r.proposals ? `검토 제안 ${r.proposals}건을 냈습니다.` : "바뀐 판정이 없습니다.", { position: "top-center" });
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "다시 판정하지 못했습니다.", { position: "top-center" });
    } finally {
      setScanning(false);
    }
  };

  const canExtract = !!data && (data.canExtract.workspace || data.canExtract.company);
  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
      <PageHeader
        title="판단 기준"
        wide
        actions={
          <>
            {ws.can("editor") && (
              <span className="flex items-center gap-1.5">
                <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} title="그날까지 나온 자료로 판정(비우면 지금)" className="h-10 rounded-xl border border-neutral-200 bg-white px-2 text-[13px]" />
                <button type="button" disabled={scanning} onClick={() => void scan()} title="사용 중 기준을 다시 판정 — 바뀐 것만 걸린 문서에 검토 제안" className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl border border-neutral-200 bg-white px-3 text-[13px] font-medium text-text-primary hover:bg-neutral-50 disabled:opacity-60">
                  {scanning && <Loader2 className="size-4 animate-spin" aria-hidden />}
                  다시 판정
                </button>
              </span>
            )}
            {canExtract && (
              <button type="button" onClick={() => setPicking(true)} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover">
                <Sparkles className="size-4" aria-hidden />
                기준 뽑기
              </button>
            )}
          </>
        }
      />
      <div className="mx-auto max-w-[1180px] px-8 pb-14">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-0.5 rounded-lg border border-neutral-200 bg-white p-0.5">
            {(["active", "draft", "archived"] as Tab[]).map((t) => (
              <button key={t} type="button" onClick={() => setTab(t)} className={cn("h-8 cursor-pointer rounded-md px-3 text-[13px]", tab === t ? "bg-neutral-100 font-semibold text-text-primary" : "text-text-secondary hover:text-text-primary")}>
                {{ active: "사용 중", draft: "승인 대기", archived: "보관" }[t]} <span className="tabular-nums">{count(t)}</span>
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            {(["all", "company", "workspace"] as Scope[]).map((s) => (
              <button key={s} type="button" onClick={() => setScope(s)} className={cn("h-8 cursor-pointer rounded-full border px-3 text-[12px]", scope === s ? "border-neutral-800 bg-neutral-800 text-white" : "border-neutral-200 bg-white text-text-secondary hover:text-text-primary")}>
                {{ all: "전체", company: "사내", workspace: "워크스페이스" }[s]}
              </button>
            ))}
          </div>
        </div>
        {data === null && <p className="text-[13px] text-text-secondary">불러오는 중…</p>}
        {data && !shown.length && <p className="rounded-[20px] bg-white px-6 py-8 text-[14px] text-text-secondary">{tab === "draft" ? "승인 대기 중인 기준이 없습니다." : tab === "active" ? "사용 중인 기준이 없습니다." : "보관한 기준이 없습니다."}</p>}
        {shown.length > 0 && (
          <div className="overflow-hidden rounded-[20px] bg-white">
            {shown.map((c) => (
              <Row key={c.id} c={c} focused={c.id === initial} onChange={replace} />
            ))}
          </div>
        )}
      </div>
      {picking && data && <ExtractDialog canCompany={data.canExtract.company} canWorkspace={data.canExtract.workspace} onClose={() => setPicking(false)} onDone={(d) => (setData(d), setTab("draft"), setPicking(false))} />}
    </div>
  );
}

function Row({ c, focused, onChange }: { c: CriterionView; focused: boolean; onChange: (c: CriterionView) => void }) {
  const ws = useWorkspace();
  const openSource = useOpenSource();
  const [open, setOpen] = useState(focused || c.status === "draft");
  const [busy, setBusy] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ title: string; direction: string; op: string; threshold: string } | null>(null);
  const [versions, setVersions] = useState<CriterionView[] | null>(null);
  const who = c.applies.name || c.applies.assetClass || "전체";

  const openAnchor = (a?: AnchorRef | null) => {
    if (!a) return;
    if (a.kind === "report" && a.sessionId) ws.nav.openReport(a.sessionId);
    else if (a.docId) openSource(a.docId, a.chunk ?? null, a.cell ?? null);
  };

  const run = async (key: string, fn: () => Promise<CriterionView>, ok: string, fail: string) => {
    setBusy(key);
    try {
      const got = await fn();
      if (ok) toast.success(ok, { position: "top-center" });
      onChange(got);
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : fail, { position: "top-center" });
    } finally {
      setBusy(null);
    }
  };

  const save = () =>
    edit &&
    void run(
      "save",
      async () => {
        const got = await patchCriterion(c.id, {
          title: edit.title,
          direction: edit.direction,
          ...(c.kind === "numeric" && Number.isFinite(Number(edit.threshold)) ? { condition: { ...c.condition, op: edit.op, threshold: Number(edit.threshold) } } : {}),
        });
        setEdit(null);
        return got;
      },
      "고쳤습니다.",
      "고치지 못했습니다.",
    );

  const loadVersions = async () => {
    try {
      setVersions(await criterionVersions(c.id, ws.workspaceId));
    } catch {
      setVersions([]);
    }
  };

  return (
    <div className={cn("border-b border-neutral-100 px-5 py-3 last:border-0", focused && "bg-neutral-50")}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full cursor-pointer items-start gap-2 text-left">
        <ChevronRight className={cn("mt-1 size-3.5 shrink-0 text-neutral-400 transition-transform", open && "rotate-90")} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5 text-[14px] font-semibold text-text-primary">
            {c.title}
            <span className="rounded border border-neutral-200 px-1 text-[11px] font-normal text-text-secondary">{c.scopeKo}</span>
            <span className="text-[12px] font-normal text-text-secondary tabular-nums">v{c.version}</span>
            {c.origin.kind === "revision" && c.status === "draft" && <span className="rounded bg-neutral-100 px-1 text-[11px] font-normal text-neutral-700">수정안</span>}
          </span>
          <span className="mt-0.5 block text-[13px] text-text-primary">
            {c.conditionText} → <b className="font-semibold">{c.directionKo}</b>
            <span className="text-text-secondary"> · 대상 {who}</span>
          </span>
        </span>
        <span className="shrink-0 text-[12px] text-text-secondary">{c.status === "active" ? `${c.approvedBy ?? ""} 승인 · ${when(c.approvedAt)}` : c.status === "draft" ? `${c.createdBy || "AI"} · ${when(c.createdAt)}` : when(c.approvedAt || c.createdAt)}</span>
      </button>
      {open && (
        <div className="mt-2 pl-5.5 text-[13px]">
          {c.source.quote && (
            <p className="leading-6 text-text-primary">
              “{c.source.quote}”
              <span className="text-text-secondary"> — {c.source.docTitle}</span>
              {c.source.anchor && (
                <button type="button" onClick={() => openAnchor(c.source.anchor)} className="ml-1.5 h-6 cursor-pointer rounded-md border border-neutral-200 px-1.5 text-[11px] text-text-primary hover:bg-neutral-50">
                  원문
                </button>
              )}
            </p>
          )}
          {c.origin.kind === "revision" && (
            <p className="mt-1 text-[12px] text-text-secondary">
              승인된 문서 ‘{c.origin.reportTitle}’에서 {c.origin.relation === "new" ? "새 기준" : "기준 수정"}
              {c.origin.why && ` — ${c.origin.why}`}
              {c.origin.reportId && (
                <button type="button" onClick={() => ws.nav.openReport(c.origin.reportId!)} className="ml-1.5 cursor-pointer underline-offset-2 hover:underline">
                  문서 열기
                </button>
              )}
            </p>
          )}
          {c.diff.length > 0 && c.base && (
            <div className="mt-2 overflow-hidden rounded-lg border border-neutral-200">
              <div className="grid grid-cols-[72px_minmax(0,1fr)_minmax(0,1fr)] gap-3 bg-neutral-50 px-3 py-1.5 text-[11px] font-semibold text-neutral-500">
                <span>바뀐 것</span>
                <span>{c.status === "draft" ? "지금" : "이전"} v{c.base.version}</span>
                <span>{c.status === "draft" ? "제안 " : ""}v{c.version}</span>
              </div>
              {c.diff.map((d) => (
                <div key={d.field} className="grid grid-cols-[72px_minmax(0,1fr)_minmax(0,1fr)] gap-3 border-t border-neutral-100 px-3 py-1.5 text-[12px]">
                  <span className="text-text-secondary">{d.field}</span>
                  <span className="text-text-secondary line-through decoration-neutral-300">{show(d.before)}</span>
                  <span className="text-text-primary">{show(d.after)}</span>
                </div>
              ))}
            </div>
          )}
          {c.conflicts.length > 0 && (
            <div className="mt-2 flex flex-col gap-0.5">
              {c.conflicts.map((x) => (
                <p key={x.id} className="text-[12px] text-text-primary">
                  충돌 · {x.title} v{x.version} — {x.why}
                  <span className="text-text-secondary"> ({x.by === "code" ? "코드 확인" : "AI 판단"})</span>
                </p>
              ))}
            </div>
          )}
          {edit && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px]">
              <input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} className="h-7 w-48 rounded-md border border-neutral-200 px-2" aria-label="이름" />
              <select value={edit.direction} onChange={(e) => setEdit({ ...edit, direction: e.target.value })} className="h-7 rounded-md border border-neutral-200 bg-white px-1" aria-label="방향">
                {DIRECTIONS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
              {c.kind === "numeric" && (
                <>
                  <span className="text-text-secondary">{c.condition.metric}</span>
                  <input value={edit.threshold} inputMode="decimal" onChange={(e) => setEdit({ ...edit, threshold: e.target.value })} className="h-7 w-16 rounded-md border border-neutral-200 px-2 tabular-nums" aria-label="기준값" />
                  <span className="text-text-secondary">{c.condition.unit}</span>
                  <select value={edit.op} onChange={(e) => setEdit({ ...edit, op: e.target.value })} className="h-7 rounded-md border border-neutral-200 bg-white px-1" aria-label="부등호">
                    {OPS.map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </>
              )}
              <Btn disabled={!!busy} onClick={save}>
                저장
              </Btn>
              <Btn onClick={() => setEdit(null)}>취소</Btn>
            </div>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-1">
            {c.status === "draft" && c.canApprove && (
              <>
                <button type="button" disabled={!!busy} onClick={() => void run("ok", () => decideCriterion(c.id, true), "승인했습니다 — 이제 AI 가 이 기준을 씁니다.", "승인하지 못했습니다.")} className="flex h-7 cursor-pointer items-center gap-1 rounded-md bg-primary px-2.5 text-[12px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
                  {busy === "ok" && <Loader2 className="size-3 animate-spin" aria-hidden />}
                  승인
                </button>
                <Btn disabled={!!busy} onClick={() => window.confirm("이 기준 초안을 버릴까요?") && void run("no", () => decideCriterion(c.id, false), "", "버리지 못했습니다.")}>
                  버리기
                </Btn>
              </>
            )}
            {c.status === "draft" && !c.canApprove && <span className="text-[12px] text-text-secondary">{c.scope === "company" ? "관리자" : "워크스페이스 소유자"}가 승인합니다</span>}
            {c.status === "draft" && (c.canApprove || ws.can("editor")) && !edit && (
              <Btn onClick={() => setEdit({ title: c.title, direction: c.direction, op: c.condition.op || ">=", threshold: String(c.condition.threshold ?? "") })}>고치기</Btn>
            )}
            {c.version > 1 || c.status !== "draft" ? <Btn onClick={() => void loadVersions()}>판 이력</Btn> : null}
          </div>
          {versions && (
            <div className="mt-2 rounded-lg bg-neutral-50 px-3 py-2">
              {versions.map((v) => (
                <p key={v.id} className="flex gap-2 py-0.5 text-[12px]">
                  <span className="w-8 shrink-0 tabular-nums text-text-secondary">v{v.version}</span>
                  <span className="w-16 shrink-0 text-text-secondary">{v.statusKo}</span>
                  <span className="min-w-0 flex-1 truncate">
                    {v.conditionText} → {v.directionKo}
                    {v.approvedBy && <span className="text-text-secondary"> · {v.approvedBy} {when(v.approvedAt)}</span>}
                  </span>
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ExtractDialog({ canCompany, canWorkspace, onClose, onDone }: { canCompany: boolean; canWorkspace: boolean; onClose: () => void; onDone: (d: CriteriaPayload) => void }) {
  const ws = useWorkspace();
  const [docs, setDocs] = useState<DocumentCard[] | null>(null);
  const [reports, setReports] = useState<SessionListItem[]>([]);
  const [pick, setPick] = useState("");
  const [scope, setScope] = useState<"company" | "workspace">(canWorkspace ? "workspace" : "company");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getDocuments(ws.workspaceId).then((d) => setDocs(d.documents ?? []), () => setDocs([]));
    listReports(ws.workspaceId).then((r) => setReports(r.filter((x) => x.hasDoc)), () => setReports([]));
  }, [ws.workspaceId]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose, busy]);

  const go = async () => {
    const [kind, ref] = pick.split(":");
    if (!ref) return;
    setBusy(true);
    try {
      const d = await extractCriteria(ws.workspaceId, { docKind: kind as "report" | "data", docRef: ref, scope });
      toast.success(d.made ? `기준 초안 ${d.made}개를 냈습니다 — 승인하면 씁니다.` : "새로 뽑을 기준이 없습니다.", { position: "top-center" });
      onDone(d);
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "기준을 뽑지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onMouseDown={() => !busy && onClose()}>
      <div onMouseDown={(e) => e.stopPropagation()} className="w-full max-w-[520px] rounded-2xl bg-white p-5 shadow-2xl">
        <h2 className="text-[17px] font-bold text-text-primary">기준 뽑기</h2>
        <label className="mt-4 block text-[12px] font-semibold text-neutral-500" htmlFor="crit-doc">
          자료·문서
        </label>
        <select id="crit-doc" value={pick} onChange={(e) => setPick(e.target.value)} className="mt-1 h-10 w-full rounded-xl border border-neutral-200 bg-white px-2 text-[13px]">
          <option value="">고르세요</option>
          <optgroup label="자료(투자정책서·하우스뷰·회의록·안건)">
            {(docs ?? []).map((d) => (
              <option key={d.id} value={`data:${d.id}`}>
                {d.title || d.label}
                {d.shared ? " · 사내 공용" : ""}
              </option>
            ))}
          </optgroup>
          {reports.length > 0 && (
            <optgroup label="AI 작업 문서">
              {reports.map((r) => (
                <option key={r.id} value={`report:${r.id}`}>
                  {r.title}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        {canCompany && canWorkspace && (
          <div className="mt-3 flex items-center gap-3 text-[13px]">
            {(["workspace", "company"] as const).map((s) => (
              <label key={s} className="flex cursor-pointer items-center gap-1.5">
                <input type="radio" checked={scope === s} onChange={() => setScope(s)} className="accent-primary" />
                {s === "company" ? "사내 공통" : "이 워크스페이스"}
              </label>
            ))}
          </div>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" disabled={busy} onClick={onClose} className="h-10 cursor-pointer rounded-xl px-4 text-[13px] text-text-secondary hover:bg-neutral-100">
            취소
          </button>
          <button type="button" disabled={busy || !pick} onClick={() => void go()} className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {busy ? "뽑는 중…" : "뽑기"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Btn({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} className="h-7 cursor-pointer rounded-md border border-neutral-200 px-2 text-[12px] text-text-primary hover:bg-neutral-50 disabled:cursor-default disabled:opacity-50">
      {children}
    </button>
  );
}
