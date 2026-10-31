"use client";

/**
 * 가정 서랍 — 문서(AI 작업 문서·올린 안건)의 가정 문장. 메뉴 없이 문서 머리 '가정'·본문 가정 줄·드라이브 '가정 표시'·홈에서 연다.
 * [가정 뽑기] → 사람이 [감시]를 켠다 → 새 자료가 오면 서버가 다시 판정한다. 판정은 조건·값 나란히 + 한 낱말(색 없음).
 * 당시 근거·지금 값은 원문 창으로 연다(얼려 둔 앵커 — BE app/anchors.py). [재심의 안건]은 '재심의 안건(예시)' 양식으로 초안을 쓴다.
 */
import { useEffect, useRef, useState } from "react";
import { useAtom, useSetAtom } from "jotai";
import { ChevronRight, Gavel, Loader2, Sparkles, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { getCommittee, runCommittee, type CommitteeResult } from "../assistants/api";
import { ApiError } from "../report/api";
import { focusStepAtom } from "../report/atoms";
import { SourceDialog, type SourceTarget } from "../report/components/viewer/SourceModal";
import { useWorkspace } from "../workspace/context";
import { FEATURES } from "../workspace/features";
import { checkAssumption, extractAssumptions, patchAssumption, writeAgenda, type AnchorRef, type Assumption } from "./api";
import { assumptionsDrawerAtom, isChanged, needsLook, takePendingDrawer, useDocAssumptions } from "./state";

const OPS = [">=", ">", "<=", "<"] as const;
const OP_KO: Record<string, string> = { ">=": "이상", ">": "초과", "<=": "이하", "<": "미만" };

const shortAt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "");

/** 워크스페이스 화면 어디서나 하나 — WorkspaceShell 에 둔다 */
export function AssumptionsDrawerHost() {
  const [open, setOpen] = useAtom(assumptionsDrawerAtom);
  useEffect(() => {
    const got = takePendingDrawer();
    if (got) setOpen(got);
  }, [setOpen]);
  if (!open) return null;
  return <AssumptionsDrawer key={open.docRef} {...open} onClose={() => setOpen(null)} />;
}

function AssumptionsDrawer({ docKind, docRef, title, focusId, onClose }: { docKind: "report" | "data"; docRef: string; title: string; focusId?: string; onClose: () => void }) {
  const ws = useWorkspace();
  const canEdit = ws.can("editor");
  const { items, loaded, setAll, replace } = useDocAssumptions(ws.workspaceId, docRef);
  const [extracting, setExtracting] = useState(false);
  const [source, setSource] = useState<SourceTarget | null>(null);
  const setFocusStep = useSetAtom(focusStepAtom);
  const [committee, setCommittee] = useState<CommitteeResult | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [fresh, setFresh] = useState(false);

  useEffect(() => {
    if (FEATURES.assistants) getCommittee(ws.workspaceId, docRef).then(setCommittee, () => undefined);
  }, [ws.workspaceId, docRef]);

  const prepare = async () => {
    setPreparing(true);
    try {
      setCommittee(await runCommittee(ws.workspaceId, docKind, docRef));
      setFresh(true);
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "심의 준비를 하지 못했습니다.", { position: "top-center" });
    } finally {
      setPreparing(false);
    }
  };

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && !source && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose, source]);

  const extract = async () => {
    setExtracting(true);
    try {
      const list = await extractAssumptions(ws.workspaceId, docKind, docRef);
      setAll(list);
      if (!list.length) toast("가정으로 볼 문장을 찾지 못했습니다.", { position: "top-center" });
    } catch {
      toast.error("가정을 뽑지 못했습니다.", { position: "top-center" });
    } finally {
      setExtracting(false);
    }
  };

  const openAnchor = (a: AnchorRef) => a.docId && a.chunk && setSource({ docId: a.docId, chunk: a.chunk, cell: a.cell ?? null, tick: Date.now() });
  const watching = items.filter((a) => a.watch);
  const candidates = items.filter((a) => !a.watch);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onMouseDown={onClose}>
      <aside onMouseDown={(e) => e.stopPropagation()} className="flex h-full w-full max-w-[480px] flex-col bg-white shadow-2xl">
        <header className="flex items-start gap-3 border-b border-neutral-200 px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-[17px] font-bold text-text-primary">가정</h2>
            <p className="truncate text-[12px] text-text-secondary">{title}</p>
          </div>
          {FEATURES.assistants && (canEdit || items.length > 0) && (
            <button type="button" disabled={preparing || extracting} onClick={() => void prepare()} title="과거 가정·판정과 회의록에서 반대 논거·미해결 질문을 원문과 함께" className="flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-neutral-200 px-3 text-[12px] font-medium text-text-primary hover:bg-neutral-50 disabled:opacity-60">
              {preparing ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Gavel className="size-3.5" aria-hidden />}
              {preparing ? "준비 중…" : "심의 준비"}
            </button>
          )}
          {canEdit && (
            <button type="button" disabled={extracting} onClick={() => void extract()} className="flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-neutral-200 px-3 text-[12px] font-medium text-text-primary hover:bg-neutral-50 disabled:opacity-60">
              {extracting ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Sparkles className="size-3.5" aria-hidden />}
              {extracting ? "뽑는 중…" : "가정 뽑기"}
            </button>
          )}
          <button type="button" aria-label="닫기" onClick={onClose} className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-text-secondary hover:bg-neutral-100">
            <X className="size-4" aria-hidden />
          </button>
        </header>
        <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {committee && <Committee key={committee.at} c={committee} fresh={fresh} onAnchor={openAnchor} />}
          {!loaded && <p className="text-[13px] text-text-secondary">불러오는 중…</p>}
          {loaded && !items.length && <p className="text-[13px] text-text-secondary">{canEdit ? "[가정 뽑기]로 이 문서가 기댄 가정 문장을 찾습니다." : "표시된 가정이 없습니다."}</p>}
          {watching.length > 0 && <GroupTitle>감시 중 {watching.length}</GroupTitle>}
          {watching.map((a) => (
            <Item key={a.id} a={a} canEdit={canEdit} focused={a.id === focusId} onChange={replace} onAnchor={openAnchor} onStep={docKind === "report" && a.step ? () => (setFocusStep(a.step), onClose()) : undefined} />
          ))}
          {candidates.length > 0 && <GroupTitle>후보 {candidates.length}</GroupTitle>}
          {candidates.map((a) => (
            <Item key={a.id} a={a} canEdit={canEdit} focused={a.id === focusId} onChange={replace} onAnchor={openAnchor} onStep={docKind === "report" && a.step ? () => (setFocusStep(a.step), onClose()) : undefined} />
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

/** 심의 준비 — 비슷한 과거 가정(판정) + 반대 논거·미해결 질문(원문 인용) + 추가 질문 */
function Committee({ c, fresh, onAnchor }: { c: CommitteeResult; fresh: boolean; onAnchor: (a: AnchorRef) => void }) {
  const ws = useWorkspace();
  const [open, setOpen] = useState(fresh);
  const count = (k: string) => c.items.filter((x) => x.kind === k).length;
  const summary = [c.past.length && `과거 가정 ${c.past.length}`, count("counter") && `반대 논거 ${count("counter")}`, count("open") && `미해결 질문 ${count("open")}`, count("ask") && `추가 질문 ${count("ask")}`].filter(Boolean).join(" · ");
  return (
    <section className="mb-4 rounded-xl bg-neutral-50 px-4 py-3">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full cursor-pointer items-center gap-1.5 text-left text-[13px] font-semibold text-text-primary">
        <ChevronRight className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} aria-hidden />
        심의 준비
        <span className="min-w-0 flex-1 truncate text-[12px] font-normal text-text-secondary">{summary || "짚을 것 없음"}</span>
        <span className="shrink-0 text-[11px] font-normal text-text-secondary">{shortAt(c.at)}</span>
      </button>
      {open && c.past.length > 0 && (
        <div className="mt-2">
          <p className="text-[12px] text-neutral-500">비슷한 과거 가정</p>
          {c.past.map((p) => (
            <div key={p.id} className="flex items-start gap-2 py-1 text-[12px]">
              <span className="min-w-0 flex-1">
                <span className="text-text-primary">“{p.quote}”</span>
                <span className="block text-text-secondary">
                  {p.docTitle}
                  {p.resultKo && (
                    <>
                      {" · "}
                      <b className="font-semibold text-text-primary">{p.resultKo}</b>
                      {p.value && ` ${p.value}`}
                    </>
                  )}
                </span>
              </span>
              {p.anchors[0] ? (
                <Btn onClick={() => onAnchor(p.anchors[0])}>원문</Btn>
              ) : (
                p.docKind === "report" && <Btn onClick={() => ws.nav.openReport(p.docRef)}>문서</Btn>
              )}
            </div>
          ))}
        </div>
      )}
      {open && c.items.length > 0 && (
        <div className="mt-2">
          {c.items.map((it, i) => (
            <div key={i} className="flex items-start gap-2 border-t border-neutral-200/70 py-1.5 text-[12px] first:border-0">
              <span className="min-w-0 flex-1 leading-5">
                <b className="font-semibold text-text-primary">{it.kindKo}</b> <span className="text-text-primary">{it.text}</span>
                {it.quote && <span className="block text-text-secondary">“{it.quote}” — {it.source}</span>}
              </span>
              {it.anchor && <Btn onClick={() => onAnchor(it.anchor!)}>원문</Btn>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function GroupTitle({ children }: { children: React.ReactNode }) {
  return <p className="mt-4 mb-1 text-[12px] font-semibold text-neutral-500 first:mt-0">{children}</p>;
}

function Item({ a, canEdit, focused, onChange, onAnchor, onStep }: { a: Assumption; canEdit: boolean; focused: boolean; onChange: (a: Assumption) => void; onAnchor: (x: AnchorRef) => void; onStep?: () => void }) {
  const ws = useWorkspace();
  const ref = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ op: string; threshold: string } | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [asOf, setAsOf] = useState("");
  const lt = a.latest;
  const changed = isChanged(a);

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "center" });
  }, [focused]);

  const run = async (key: string, fn: () => Promise<Assumption>, fail: string) => {
    setBusy(key);
    try {
      onChange(await fn());
    } catch {
      toast.error(fail, { position: "top-center" });
    } finally {
      setBusy(null);
    }
  };

  const agenda = async () => {
    if (!window.confirm(`이 ${a.roleKo}·당시 근거·지금 값으로 '재심의 안건' 초안을 씁니다. 다 쓰면 알림이 옵니다.`)) return;
    setBusy("agenda");
    try {
      onChange(await writeAgenda(a.id));
      toast.success("재심의 안건을 쓰기 시작했습니다. 다 쓰면 알림이 옵니다.", { position: "top-center" });
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "재심의 안건을 시작하지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(null);
    }
  };

  // 당시 근거 = 문장의 인용(AI 작업 문서) 또는 올린 안건의 그 문단 / 지금 값 = 최근 판정의 원문(전년 비교면 두 칸)
  const basis = a.basis.length ? a.basis : a.docKind === "data" && a.anchor.docId ? [a.anchor] : [];
  const nowAnchors = lt?.anchors ?? [];
  const nowLabel = (i: number) => (a.kind === "numeric" ? (i === 0 ? lt?.value.period : lt?.value.base) || `값 ${i + 1}` : "근거 문단");

  return (
    <div ref={ref} className={cn("border-b border-neutral-100 py-3 last:border-0", focused && "rounded-lg bg-neutral-50 px-2")}>
      <div className="flex items-start gap-3">
        <p className="min-w-0 flex-1 text-[14px] leading-6 text-text-primary">
          {onStep ? (
            <button type="button" onClick={onStep} title="문서에서 이 문장 보기" className="cursor-pointer text-left hover:text-primary">
              “{a.quote}”
            </button>
          ) : (
            <>“{a.quote}”</>
          )}
        </p>
        <label className={cn("flex shrink-0 items-center gap-1.5 text-[12px] text-text-secondary", canEdit && "cursor-pointer")}>
          <input type="checkbox" checked={a.watch} disabled={!canEdit || !!busy} onChange={(e) => void run("watch", () => patchAssumption(a.id, { watch: e.target.checked }), "바꾸지 못했습니다.")} className="size-4 accent-primary" />
          감시
        </label>
      </div>
      <p className="mt-0.5 text-[12px] leading-5 text-text-secondary">
        <button
          type="button"
          disabled={!canEdit || !!busy}
          title={canEdit ? "가정 ↔ 재심의 조건 바꾸기" : undefined}
          onClick={() => void run("role", () => patchAssumption(a.id, { role: a.role === "trigger" ? "assumption" : "trigger" }), "바꾸지 못했습니다.")}
          className="mr-1.5 inline-block rounded border border-neutral-200 px-1 text-[11px] leading-4 text-text-primary enabled:cursor-pointer enabled:hover:bg-neutral-50"
        >
          {a.roleKo}
        </button>
        {[a.target.name, a.conditionText].filter(Boolean).join(" · ")}
      </p>
      {editing && (
        <div className="mt-2 flex items-center gap-1.5 text-[12px]">
          <span className="text-text-secondary">{a.condition.ledgerMetric || a.condition.metric}</span>
          <select value={editing.op} onChange={(e) => setEditing({ ...editing, op: e.target.value })} className="h-7 rounded-md border border-neutral-200 bg-white px-1">
            {OPS.map((o) => (
              <option key={o} value={o}>
                {OP_KO[o]}
              </option>
            ))}
          </select>
          <input value={editing.threshold} inputMode="decimal" onChange={(e) => setEditing({ ...editing, threshold: e.target.value })} className="h-7 w-20 rounded-md border border-neutral-200 px-2 tabular-nums" />
          <span className="text-text-secondary">{a.condition.unit}</span>
          <button
            type="button"
            disabled={!!busy || !Number.isFinite(Number(editing.threshold))}
            onClick={() =>
              void run(
                "cond",
                async () => {
                  await patchAssumption(a.id, { condition: { op: editing.op, threshold: Number(editing.threshold) } });
                  setEditing(null);
                  return checkAssumption(a.id);
                },
                "조건을 바꾸지 못했습니다.",
              )
            }
            className="h-7 cursor-pointer rounded-md bg-primary px-2.5 text-white hover:bg-primary-hover disabled:opacity-50"
          >
            저장
          </button>
          <button type="button" onClick={() => setEditing(null)} className="h-7 cursor-pointer rounded-md px-2 text-text-secondary hover:bg-neutral-100">
            취소
          </button>
        </div>
      )}
      {lt && (
        <p className="mt-1.5 text-[13px] text-text-primary">
          지금 <span className="tabular-nums">{lt.value.display || "—"}</span> · <b className="font-semibold">{lt.resultKo || lt.result}</b>
          {changed && lt.prevKo && <span className="text-text-secondary"> (바뀜: {lt.prevKo} → {lt.resultKo})</span>}
          <span className="ml-1.5 text-[11px] text-text-secondary">
            {shortAt(lt.at)}
            {lt.asOf && ` · 기준일 ${lt.asOf}`}
          </span>
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1">
        {basis.slice(0, 3).map((b, i) => (
          <Btn key={`b${i}`} onClick={() => onAnchor(b)} title={b.quote}>
            {i === 0 ? "당시 근거" : `근거 ${i + 1}`}
          </Btn>
        ))}
        {nowAnchors.slice(0, 2).map((x, i) => (
          <Btn key={`n${i}`} onClick={() => onAnchor(x)} title={x.quote}>
            {nowLabel(i)} 원문
          </Btn>
        ))}
        <Btn disabled={!!busy} onClick={() => void run("check", () => checkAssumption(a.id), "판정하지 못했습니다.")}>
          {busy === "check" ? "판정 중…" : "다시 판정"}
        </Btn>
        {needsLook(a) && canEdit && (
          <Btn disabled={!!busy} onClick={() => void run("ack", () => patchAssumption(a.id, { acknowledge: true }), "바꾸지 못했습니다.")} title="확인했음 — 홈 '오늘 확인할 것'에서 뺀다">
            넘기기
          </Btn>
        )}
        {canEdit && lt?.alert && !lt.agendaId && (
          <Btn disabled={!!busy || lt.agendaStatus === "writing"} onClick={() => void agenda()}>
            {lt.agendaStatus === "writing" ? "안건 쓰는 중…" : lt.agendaStatus === "error" ? "재심의 안건 다시" : "재심의 안건"}
          </Btn>
        )}
        {lt?.agendaId && <Btn onClick={() => ws.nav.openReport(lt.agendaId!)}>재심의 안건 열기</Btn>}
        {canEdit && a.kind === "numeric" && !editing && <Btn onClick={() => setEditing({ op: a.condition.op || ">=", threshold: String(a.condition.threshold ?? "") })}>조건</Btn>}
        {a.history.length > 0 && <Btn onClick={() => setShowHistory((v) => !v)}>이력 {a.history.length}</Btn>}
        {canEdit && (
          <Btn disabled={!!busy} onClick={() => window.confirm("이 가정을 목록에서 뺄까요?") && void run("dismiss", () => patchAssumption(a.id, { dismiss: true }), "빼지 못했습니다.")}>
            빼기
          </Btn>
        )}
      </div>
      {showHistory && (
        <div className="mt-2 rounded-lg bg-neutral-50 px-3 py-2">
          {a.history.map((h) => (
            <p key={h.id} className="flex gap-2 py-0.5 text-[12px]">
              <span className="w-[92px] shrink-0 text-text-secondary tabular-nums">{shortAt(h.at)}</span>
              <span className="min-w-0 flex-1 truncate">
                <b className="font-semibold">{h.resultKo}</b> · {h.value.display || "—"}
                {h.asOf && <span className="text-text-secondary"> · 기준일 {h.asOf}</span>}
              </span>
            </p>
          ))}
          <div className="mt-1.5 flex items-center gap-1.5 text-[12px]">
            <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="h-7 rounded-md border border-neutral-200 bg-white px-1.5" />
            <Btn disabled={!asOf || !!busy} onClick={() => void run("asof", () => checkAssumption(a.id, asOf), "판정하지 못했습니다.")}>
              {busy === "asof" ? "판정 중…" : "그날 기준으로 판정"}
            </Btn>
          </div>
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
