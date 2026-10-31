"use client";

/**
 * 검토 목록 — 작성자가 아닌 멤버가 문서를 열면 왼쪽 칸(에이전트 대화 자리)에 보인다(대화는 작성자의 것).
 * 위: 검토 요청(요청한 사람·메모), 가운데: 섹션별 '근거 달린 문장 + 그 문장 속 숫자' — 문장을 누르면 인용한 원문(문장 속 금액과 같은 칸 강조),
 * 숫자를 누르면 그 숫자의 원본 칸(계산값이면 계산에 쓴 첫 원본). 판정 색·확인 표시 없이 원본 연결만(전문가가 눈으로 맞춘다).
 * 아래: 검토를 요청받은 사람에게 의견 + [검토 완료](승인 — 작성자에게 알림, 검토 작업 끝).
 */
import { useMemo, useState } from "react";
import { useAtomValue } from "jotai";
import { CheckCircle2, FileText } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { approveDoc } from "../../../workspace/api";
import { useWorkspace } from "../../../workspace/context";
import { documentsAtom, numbersAtom, readinessAtom, reportAtom, reportOwnerAtom, sessionAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import type { CiteAnchor, NumberItem, NumberSourceRef, ReportBlock } from "../../types";

type Row = { sentence: string; anchors: CiteAnchor[]; nums: NumberItem[] };
type Part = { step: string; title: string; rows: Row[] };

const norm = (s: string) => s.replace(/\[\d+(?:,\s*\d+)*\]/g, "").replace(/\s+/g, "");

function whereOf(x: NumberSourceRef): string {
  return [x.label, x.page ? `p.${x.page}` : x.sheet ? `시트 ${x.sheet}` : "", x.metric && x.period ? `${x.metric} · ${x.period}` : ""].filter(Boolean).join(" · ");
}

/** 이 숫자의 원본으로 보일 것 — 문장이 인용한 자료가 따로 있는데 원장에서 다른 자료의 같은 값만 찾은 것('손실 폭 0.4%' → KOSPI 1주 변동)은 연결로 보이지 않는다 */
function linked(n: NumberItem): NumberSourceRef | null {
  const s = n.source;
  if (!s) return null;
  return s.via === "ledger" && n.cited.length && !n.cited.some((c) => c.docId === s.docId) ? null : s;
}

/** 숫자 → 원본 한 줄(계산값은 계산 이름) */
function sourceLine(n: NumberItem): string {
  const s = linked(n);
  if (s) return whereOf(s);
  if (n.calc) return `계산 · ${n.calc.label}`;
  if (n.status === "input") return "입력값";
  return "—";
}

function ago(iso: string): string {
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  return m < 1 ? "방금" : m < 60 ? `${m}분 전` : m < 1440 ? `${Math.round(m / 60)}시간 전` : `${Math.round(m / 1440)}일 전`;
}

export function ReviewPanel() {
  const report = useAtomValue(reportAtom);
  const numbers = useAtomValue(numbersAtom);
  const readiness = useAtomValue(readinessAtom);
  const session = useAtomValue(sessionAtom);
  const owner = useAtomValue(reportOwnerAtom);
  const documents = useAtomValue(documentsAtom);
  const ws = useWorkspace();
  const actions = useReportActions();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const parts = useMemo<Part[]>(() => {
    const out: Part[] = [];
    const byStep = new Map<string, Part>();
    for (const b of (report?.blocks ?? []) as ReportBlock[]) {
      if (b.kind === "heading") {
        const p = { step: b.step, title: b.text, rows: [] };
        out.push(p);
        byStep.set(b.step, p);
        continue;
      }
      const cites = b.kind === "para" ? b.cites : b.kind === "list" ? b.items.flatMap((it) => it.cites) : [];
      const p = byStep.get((b as { step?: string }).step ?? "");
      if (!p) continue;
      for (const c of cites) if (!p.rows.some((r) => r.sentence === c.sentence)) p.rows.push({ sentence: c.sentence, anchors: c.anchors, nums: [] });
    }
    // 숫자는 같은 섹션에서 그 숫자가 든 문장에 붙인다 — 인용 없는 문장의 숫자는 그 문장으로 한 줄
    for (const key of numbers?.order ?? []) {
      const n = numbers?.items[key];
      const p = n ? byStep.get(n.step) : undefined;
      if (!n || !p) continue;
      const s = norm(n.sentence);
      const row = p.rows.find((r) => norm(r.sentence) === s) ?? p.rows.find((r) => norm(r.sentence).includes(s) || s.includes(norm(r.sentence)));
      if (row) {
        if (!row.nums.some((x) => x.key === n.key)) row.nums.push(n);
      } else p.rows.push({ sentence: n.sentence, anchors: n.cited.map((c) => ({ ...c, n: 0 })), nums: [n] });
    }
    return out.filter((p) => p.rows.length);
  }, [report, numbers]);

  const label = (docId: string) => documents.find((d) => d.id === docId)?.label ?? "자료";
  const openSentence = (r: Row) => r.anchors[0] && actions.openDocument(r.anchors[0].docId, r.anchors[0].chunk, null, r.sentence);
  const openNumber = (n: NumberItem) => {
    const src = linked(n) ?? n.calc?.inputs[0];
    if (src) actions.openDocument(src.docId, src.chunk, src.cell);
    else if (n.cited[0]) actions.openDocument(n.cited[0].docId, n.cited[0].chunk, null, n.sentence);
  };

  const req = readiness?.reviewRequest ?? null;
  const approval = session?.approval;
  const canApprove = approval?.status === "review" && approval.reviewerId === ws.me.id;
  const done = async () => {
    if (!session) return;
    setBusy(true);
    try {
      await approveDoc(session.id, note.trim());
      toast.success("검토를 마쳤습니다 — 작성자에게 알렸습니다.", { position: "top-center" });
      setNote("");
      await actions.reload();
    } catch {
      toast.error("검토를 마치지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };
  const nums = parts.reduce((k, p) => k + p.rows.reduce((j, r) => j + r.nums.length, 0), 0);
  const rows = parts.reduce((k, p) => k + p.rows.length, 0);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-neutral-100 px-4 py-3">
        <p className="text-[13px] font-semibold text-text-primary">{owner ? `${owner.name} ${owner.title}`.trim() : "작성자"}님의 문서</p>
        {req ? (
          <p className="mt-0.5 text-[12px] leading-5 text-text-secondary">
            {ws.nameOf(req.requestedBy)} · {ago(req.requestedAt)} 검토 요청{req.note ? ` — “${req.note}”` : ""}
          </p>
        ) : (
          <p className="mt-0.5 text-[12px] leading-5 text-text-secondary">본문과 근거를 볼 수 있습니다. 에이전트와 나눈 대화는 작성자에게만 보입니다.</p>
        )}
      </div>

      <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-3 py-3">
        <p className="mb-2 px-1 text-[12px] font-semibold text-text-secondary">
          섹션별 근거 <span className="font-normal">· 근거 문장 {rows} · 숫자 {nums}</span>
        </p>
        {!parts.length && <p className="px-1 py-6 text-center text-[12px] text-text-secondary">{numbers ? "근거가 달린 문장이 없습니다." : "불러오는 중…"}</p>}
        <div className="flex flex-col gap-3">
          {parts.map((p) => (
            <section key={p.step} className="rounded-xl bg-white ring-1 ring-neutral-200">
              <button type="button" onClick={() => actions.openSection(p.step)} className="w-full cursor-pointer border-b border-neutral-100 px-3 py-2 text-left text-[13px] font-semibold text-text-primary hover:text-primary">
                {p.title}
              </button>
              <ul className="divide-y divide-neutral-100">
                {p.rows.map((r, i) => (
                  <li key={i} className="px-3 py-2">
                    <button type="button" disabled={!r.anchors.length} onClick={() => openSentence(r)} title={r.anchors.length ? "인용한 원문 보기" : undefined} className={cn("line-clamp-3 w-full text-left text-[12px] leading-5 text-text-primary", r.anchors.length ? "cursor-pointer hover:text-primary" : "cursor-default")}>
                      {r.sentence}
                    </button>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      {r.anchors
                        .filter((a, k, xs) => xs.findIndex((x) => x.docId === a.docId) === k)
                        .map((a) => (
                          <button key={`${a.docId}${a.chunk}`} type="button" onClick={() => actions.openDocument(a.docId, a.chunk, null, r.sentence)} className="flex max-w-full cursor-pointer items-center gap-1 rounded-md bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-600 hover:bg-primary-soft hover:text-primary">
                            <FileText className="size-3 shrink-0" aria-hidden />
                            <span className="truncate">{label(a.docId)}</span>
                          </button>
                        ))}
                      {r.nums.map((n) => (
                        <button key={n.key} type="button" onClick={() => openNumber(n)} title={sourceLine(n)} className="flex max-w-full cursor-pointer items-baseline gap-1 rounded-md px-1.5 py-0.5 text-[11px] ring-1 ring-neutral-200 hover:bg-primary-soft hover:ring-primary-soft-border">
                          <span className="font-semibold text-text-primary tabular-nums">{n.raw}</span>
                          <span className="truncate text-text-secondary">{sourceLine(n)}</span>
                        </button>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>

      {canApprove ? (
        <div className="shrink-0 border-t border-neutral-200 bg-white px-3 py-3">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="검토 의견(작성자에게 갑니다)" className="w-full resize-none rounded-lg border border-neutral-200 px-2.5 py-2 text-[12px] outline-none focus:border-primary" />
          <button type="button" disabled={busy} onClick={() => void done()} className="mt-2 flex h-9 w-full cursor-pointer items-center justify-center gap-1.5 rounded-lg bg-primary text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
            <CheckCircle2 className="size-4" aria-hidden />
            검토 완료
          </button>
        </div>
      ) : approval?.status === "approved" ? (
        <div className="shrink-0 border-t border-neutral-200 bg-white px-4 py-3 text-[12px] text-text-secondary">
          <span className="font-semibold text-text-primary">검토 완료</span> · {ws.nameOf(approval.by)}
          {approval.at ? ` · ${ago(approval.at)}` : ""}
          {approval.note ? <p className="mt-0.5 text-text-primary">“{approval.note}”</p> : null}
        </div>
      ) : null}
    </div>
  );
}
