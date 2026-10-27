"use client";

/**
 * 숫자 출처 탭 — 리포트 본문 숫자마다 원본(자료 · 시트/쪽 · 칸) 또는 계산식을 이어 준다. 판정 문구·색 없이 연결만 보이고,
 * 원본 칸을 바로 열어 사람이 눈으로 맞춰 본다. 위: 고른 숫자(문장 · 원본 칸 또는 계산식 · 자료마다 다른 값) + 원문 미리보기, 아래: 섹션별 숫자 목록.
 * 판정(status)은 BE 가 그대로 낸다 — 화면은 LINKED_NUMBER(source·calc)만 "연결됨"으로 쓴다.
 * 자료마다 값이 다른 숫자는 여기서 자료별 값을 보고 채택한다(본문 아래 경고 카드 대신). 숫자별 사람 확인 표시는 FEATURES.numberSignoff.
 */
import { useEffect, useMemo, useState } from "react";
import { useAtomValue } from "jotai";
import { Calculator, Check, CheckCircle2, ChevronLeft, ChevronRight, FileText, Loader2, RefreshCw, Undo2 } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { useWorkspaceId } from "../../../workspace/context";
import { FEATURES } from "../../../workspace/features";
import { canChatAtom, documentsAtom, numberFocusAtom, numbersAtom, readinessAtom } from "../../atoms";
import { LINKED_NUMBER } from "../../constants";
import { useReportActions } from "../../hooks/useReportStudio";
import type { ConflictCard, NumberItem } from "../../types";
import { AdoptReason } from "../report/AdoptReason";
import { DocViewerBody } from "../viewer/DocViewerBody";

type Loc = { docId: string; chunk: string; cell: [number, number] | null };

function where(x: { page: number | null; sheet: string | null; cell: [number, number] | null }): string {
  const loc = x.page ? `p.${x.page}` : x.sheet ? `시트 ${x.sheet}` : "";
  const cell = x.cell ? `${x.cell[0] + 1}행 ${x.cell[1] + 1}열` : "";
  return [loc, cell].filter(Boolean).join(" · ");
}

/** 목록 한 줄의 원본 요약 */
function origin(x: NumberItem): string {
  if (x.status === "source" && x.source) return [x.source.label, where(x.source)].filter(Boolean).join(" · ");
  if (x.status === "calc" && x.calc) return `계산 · ${x.calc.label}`;
  if (x.status === "input") return "입력값";
  return "—";
}

function Highlight({ text, mark }: { text: string; mark: string }) {
  const i = mark ? text.indexOf(mark) : -1;
  if (i < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, i)}
      <mark className="rounded bg-[#fff1b8] px-0.5 text-text-primary">{mark}</mark>
      {text.slice(i + mark.length)}
    </>
  );
}

export function NumberPanel() {
  const actions = useReportActions();
  const workspaceId = useWorkspaceId();
  const report = useAtomValue(numbersAtom);
  const readiness = useAtomValue(readinessAtom);
  const docs = useAtomValue(documentsAtom);
  const focus = useAtomValue(numberFocusAtom);
  const [key, setKey] = useState<string | null>(null);
  const [preview, setPreview] = useState<(Loc & { tick: number }) | null>(null);

  const items = useMemo(() => (report ? report.order.map((k) => report.items[k]).filter(Boolean) : []), [report]);
  const sections = useMemo(() => {
    const out: { step: string; title: string; items: NumberItem[] }[] = [];
    for (const x of items) {
      const last = out[out.length - 1];
      if (last?.step === x.step) last.items.push(x);
      else out.push({ step: x.step, title: x.section, items: [x] });
    }
    return out;
  }, [items]);

  // 본문에서 누른 숫자 → 그 숫자. 없으면 첫 숫자
  useEffect(() => {
    if (focus?.key) setKey(focus.key);
  }, [focus]);
  useEffect(() => {
    if (!report) return;
    if (!key || !report.items[key]) setKey(items[0]?.key ?? null);
  }, [report, key, items]);

  const it = key && report ? report.items[key] : null;
  // 숫자를 바꿀 때만 미리보기를 새로(채택 뒤 판정을 다시 받아도 그대로)
  useEffect(() => {
    const ref = it?.source ?? it?.calc?.inputs[0];
    setPreview(ref ? { docId: ref.docId, chunk: ref.chunk, cell: ref.cell, tick: Date.now() } : null);
  }, [it?.key]);

  if (!report) return <p className="px-4 py-6 text-sm text-text-secondary">불러오는 중…</p>;
  if (!items.length) return <p className="px-4 py-6 text-sm text-text-secondary">본문에 숫자가 없습니다.</p>;

  const idx = it ? items.findIndex((x) => x.key === it.key) : -1;
  const go = (d: number) => actions.openNumber(items[(Math.max(idx, 0) + d + items.length) % items.length].key);
  const show = (x: Loc) => setPreview({ docId: x.docId, chunk: x.chunk, cell: x.cell, tick: Date.now() });
  const conflict = it?.group ? readiness?.flags[it.step]?.conflicts.find((c) => c.key === it.group!.key) : undefined;
  const linked = items.filter((x) => LINKED_NUMBER.has(x.status)).length;
  const previewDoc = preview ? docs.find((d) => d.id === preview.docId) : null;

  return (
    <div className="thin-scrollbar flex min-h-0 flex-1 flex-col overflow-y-auto">
      {/* 고른 숫자 */}
      {it && (
        <div className="border-b border-neutral-100 px-4 py-3">
          <div className="flex items-center justify-between gap-2">
            <span className="min-w-0">
              <span className="num block text-[20px] leading-7 font-bold text-text-primary">{it.raw}</span>
              <span className="block truncate text-[11px] text-text-secondary">{it.section}</span>
            </span>
            {items.length > 1 && (
              <span className="flex shrink-0 items-center gap-0.5 text-[11px] text-text-secondary tabular-nums">
                <button type="button" aria-label="이전 숫자" onClick={() => go(-1)} className="cursor-pointer rounded p-1 hover:bg-neutral-100">
                  <ChevronLeft className="size-4" aria-hidden />
                </button>
                {idx + 1}/{items.length}
                <button type="button" aria-label="다음 숫자" onClick={() => go(1)} className="cursor-pointer rounded p-1 hover:bg-neutral-100">
                  <ChevronRight className="size-4" aria-hidden />
                </button>
              </span>
            )}
          </div>
          <p className="mt-2 rounded-lg bg-neutral-50 px-3 py-2 text-[13px] leading-6 text-text-primary">
            <Highlight text={it.sentence} mark={it.raw} />
          </p>

          {it.status === "source" && it.source && (
            <button type="button" onClick={() => show(it.source!)} className="mt-2.5 w-full cursor-pointer rounded-lg border border-neutral-200 px-3 py-2 text-left hover:border-primary-soft-border hover:bg-primary-soft/40">
              <span className="flex items-center gap-1.5 text-[12px] text-text-primary">
                <FileText className="size-3.5 shrink-0 text-primary" aria-hidden />
                <span className="truncate font-medium">{it.source.label}</span>
                <span className="shrink-0 text-text-secondary">{where(it.source)}</span>
              </span>
              <span className="mt-1 block text-[12px] leading-5 text-text-secondary">
                {it.source.metric && `${it.source.metric} · ${it.source.period}${it.source.column && it.source.column !== it.source.period ? ` (${it.source.column})` : ""} = `}
                <b className="text-text-primary">{it.source.display}</b>
              </span>
            </button>
          )}
          {it.status === "calc" && it.calc && (
            <div className="mt-2.5 rounded-lg border border-neutral-200 px-3 py-2">
              <p className="flex items-center gap-1.5 text-[12px] font-medium text-text-primary">
                <Calculator className="size-3.5 text-primary" aria-hidden />
                {it.calc.label}
              </p>
              <p className="mt-1 text-[12px] leading-5 text-text-secondary">
                {it.calc.readable}
                {it.calc.display && ` = ${it.calc.display}`}
              </p>
              {it.calc.inputs.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {it.calc.inputs.map((x, n) => (
                    <button key={n} type="button" onClick={() => show(x)} className="cursor-pointer rounded bg-primary-soft px-1.5 py-0.5 text-[11px] text-primary hover:underline">
                      {x.metric} {x.period} {x.display}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {!LINKED_NUMBER.has(it.status) && <p className="mt-2 text-[12px] text-text-secondary">{it.status === "input" ? "사용자가 넣은 값입니다." : "연결된 원본이 없습니다."}</p>}

          {conflict ? (
            <ConflictValues card={conflict} canChoose={Boolean(readiness?.canChoose)} onShow={show} />
          ) : (
            it.group &&
            it.group.values.length > 1 && (
              <p className="mt-2 text-[12px] text-text-secondary">
                자료별 값 {it.group.values.join(" / ")}
                {it.group.chosen && ` · 채택 ${it.group.chosen}`}
              </p>
            )
          )}
          {it.flags.includes("notChosen") && it.group?.chosen && <RewriteToChosen it={it} chosen={it.group.chosen} />}

          {FEATURES.numberSignoff && <Signoff it={it} canConfirm={report.canConfirm} />}
        </div>
      )}

      {/* 원문 미리보기 */}
      {preview && previewDoc && (
        <div className="flex h-[300px] shrink-0 flex-col border-b border-neutral-100">
          {preview.chunk && (
            <button
              type="button"
              onClick={() => actions.openDocument(preview.docId, preview.chunk, preview.cell)}
              className="mx-3 mt-2 shrink-0 cursor-pointer self-start rounded-md bg-neutral-100 px-2 py-0.5 text-[11px] font-medium text-neutral-700 hover:bg-primary-soft hover:text-primary"
            >
              원본 파일에서 확인
            </button>
          )}
          <div className="min-h-0 flex-1">
            <DocViewerBody workspaceId={workspaceId} doc={previewDoc} focusChunk={preview.chunk} focusCell={preview.cell} tick={preview.tick} />
          </div>
        </div>
      )}

      {/* 목록 */}
      <div className="px-2 py-2">
        <p className="px-2 py-1 text-[11px] text-text-secondary">
          숫자 {items.length} · 원본 연결 {linked}
        </p>
        {sections.map((s) => (
          <div key={s.step}>
            <p className="truncate px-2 pt-2.5 pb-1 text-[11px] font-semibold text-text-secondary">{s.title}</p>
            {s.items.map((x) => (
              <button
                key={x.key}
                type="button"
                onClick={() => actions.openNumber(x.key)}
                title={x.sentence}
                className={cn("flex w-full cursor-pointer items-baseline gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-neutral-50", it?.key === x.key && "bg-primary-soft/60 hover:bg-primary-soft/60")}
              >
                <b className="num shrink-0 text-[12px] text-text-primary">{x.raw}</b>
                <span className="min-w-0 flex-1 truncate text-[11px] text-text-secondary">{origin(x)}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/** 자료마다 다른 값 — 자료별 값과 원문 칸(누르면 미리보기), 편집자 이상은 채택(결정 기록에 남는다) */
function ConflictValues({ card, canChoose, onShow }: { card: ConflictCard; canChoose: boolean; onShow: (x: Loc) => void }) {
  const actions = useReportActions();
  const [asking, setAsking] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const choose = async (figureId: string, reason: string) => {
    setBusy(figureId);
    if (await actions.chooseConflict(card.key, figureId, reason)) {
      setAsking(null);
      toast.success("채택했습니다. 다시 쓰면 채택값을 씁니다.", { position: "top-center" });
    }
    setBusy(null);
  };

  return (
    <div className="mt-2.5">
      <p className="text-[11px] font-semibold text-text-secondary">자료마다 다른 값</p>
      <ul className="mt-1 flex flex-col gap-1">
        {card.values.map((v) => (
          <li key={v.figureId} className="flex flex-wrap items-center gap-1.5 rounded-lg border border-neutral-200 px-2.5 py-1.5 text-[12px]">
            <b className="num text-text-primary">{v.display}</b>
            {v.docs.map((d) => (
              <button key={d.figureId} type="button" onClick={() => onShow(d)} className="cursor-pointer rounded bg-primary-soft px-1.5 py-0.5 text-[10px] text-primary hover:underline">
                {[d.label, where(d)].filter(Boolean).join(" · ")}
              </button>
            ))}
            {canChoose && asking !== v.figureId && (
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => setAsking(v.figureId)}
                className="ml-auto inline-flex cursor-pointer items-center gap-1 rounded-md border border-neutral-200 px-2 py-0.5 text-[11px] text-text-secondary hover:bg-neutral-50 hover:text-text-primary disabled:opacity-50"
              >
                <Check className="size-3" aria-hidden />
                채택
              </button>
            )}
            {asking === v.figureId && <AdoptReason display={v.display} busy={busy === v.figureId} onSubmit={(reason) => void choose(v.figureId, reason)} onCancel={() => setAsking(null)} />}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 채택한 뒤에도 본문이 다른 값을 쓸 때 — 다시 쓰기 문장을 입력창에 넣는다(작성자만) */
function RewriteToChosen({ it, chosen }: { it: NumberItem; chosen: string }) {
  const actions = useReportActions();
  const canChat = useAtomValue(canChatAtom);
  if (!canChat) return null;
  const what = it.source ? `${it.source.metric} ${it.source.period} ` : "";
  return (
    <button type="button" onClick={() => actions.draft(`'${it.section}' 섹션을 채택값(${what}${chosen}) 기준으로 다시 써줘`)} className="mt-1.5 inline-flex cursor-pointer items-center gap-1 text-[11px] text-primary hover:underline">
      <RefreshCw className="size-3" aria-hidden />
      채택값 기준으로 다시 쓰기
    </button>
  );
}

/** 숫자별 사람 확인 표시(FEATURES.numberSignoff) */
function Signoff({ it, canConfirm }: { it: NumberItem; canConfirm: boolean }) {
  const actions = useReportActions();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const confirm = async (yes: boolean) => {
    if (busy) return;
    setBusy(true);
    if (await actions.confirmNumber(it.key, yes, note, it.raw)) setNote("");
    setBusy(false);
  };
  if (it.confirmed) {
    return (
      <div className="mt-3 flex items-start justify-between gap-2 rounded-lg bg-neutral-50 px-3 py-2 text-[12px] text-text-secondary">
        <span className="flex items-start gap-1.5">
          <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
          <span>
            {it.confirmed.byName} 확인 · {new Date(it.confirmed.at).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
            {it.confirmed.note && <span className="block text-text-primary">“{it.confirmed.note}”</span>}
          </span>
        </span>
        {canConfirm && (
          <button type="button" disabled={busy} onClick={() => void confirm(false)} className="flex shrink-0 cursor-pointer items-center gap-1 text-[11px] hover:underline">
            <Undo2 className="size-3" aria-hidden />
            취소
          </button>
        )}
      </div>
    );
  }
  if (!canConfirm) return null;
  return (
    <div className="mt-3 flex items-center gap-1.5">
      <input value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && void confirm(true)} placeholder="메모(선택)" className="min-w-0 flex-1 rounded-lg border border-neutral-200 px-2.5 py-1.5 text-[12px] outline-none focus:border-primary" />
      <button type="button" disabled={busy} onClick={() => void confirm(true)} className="flex shrink-0 cursor-pointer items-center gap-1 rounded-lg border border-neutral-200 px-3 py-1.5 text-[12px] text-text-primary hover:bg-neutral-50 disabled:opacity-50">
        {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Check className="size-3.5" aria-hidden />}
        확인함
      </button>
    </div>
  );
}
