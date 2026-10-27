"use client";

/**
 * 양식 샘플 카드 — 올린 Word·PDF 에서 찾은 표·차트를 우리 엔진으로 다시 그려 하나씩 "등록할까요?"(등록·고쳐서 등록·건너뛰기),
 * 이어서 리포트 양식(섹션·안내·자리)을 한꺼번에 등록한다. 값은 샘플의 것 — 등록하면 열·행 종류만 양식이 된다.
 * 대화(ImportCards — 작업 화면 액션)와 양식 메뉴(ImportCardList — 콜백)가 같은 카드를 쓴다.
 */
import { useState } from "react";
import { BarChart3, Check, LayoutTemplate, LineChart, Loader2, Table2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { TemplateDialog } from "../../../research/TemplateDialog";
import type { TemplateScope, TemplateSpec } from "../../../research/types";
import { useWorkspace } from "../../../workspace/context";
import { useReportActions } from "../../hooks/useReportStudio";
import type { ImportBox, ImportCard } from "../../types";
import { AssetBlockView } from "../report/FormatBlock";

const KIND_LABEL: Record<string, string> = { company: "기업", period: "기간", document: "문서", label: "항목" };

export type ImportItemBody = { action: "register" | "skip"; name?: string; scope?: TemplateScope; spec?: Partial<TemplateSpec> };
export type ImportFormatBody = { name: string; scope: TemplateScope };

function ScopePick({ value, onChange }: { value: TemplateScope; onChange: (v: TemplateScope) => void }) {
  const ws = useWorkspace();
  return (
    <select value={value} onChange={(e) => onChange(e.target.value as TemplateScope)} aria-label="범위" className="h-8 cursor-pointer rounded-lg bg-neutral-100 px-2 text-[12px] font-medium text-neutral-700 outline-none">
      <option value="user">나만</option>
      {ws.can("editor") && <option value="workspace">워크스페이스</option>}
      {ws.role === "owner" && <option value="company">사내</option>}
    </select>
  );
}

function specLine(c: ImportCard): string {
  const items = c.spec.items.filter((i) => !i.hidden).map((i) => `${i.label}${i.unit ? `(${i.unit}${i.type === "calc" ? ", 계산" : ""})` : i.type === "calc" ? "(계산)" : ""}`);
  return `행: ${c.spec.rows ? `${c.spec.rows.length}개 고정` : (KIND_LABEL[c.spec.subject.kind] ?? c.spec.subject.label)} · 열: ${items.join(" · ")}`;
}

function ItemCard({ card, onItem }: { card: ImportCard; onItem: (n: number, body: ImportItemBody) => Promise<unknown> }) {
  const [scope, setScope] = useState<TemplateScope>("user");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const Icon = card.kind === "chart" ? (card.spec.chart?.type === "line" ? LineChart : BarChart3) : Table2;
  const run = async (body: ImportItemBody) => {
    setBusy(true);
    await onItem(card.n, body);
    setBusy(false);
  };

  return (
    <div className={cn("rounded-2xl border bg-white p-4", card.state === "pending" ? "border-neutral-200" : "border-neutral-100 opacity-80")}>
      <div className="flex items-start gap-2.5">
        <Icon className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-semibold text-text-primary">{card.title}</p>
          <p className="mt-0.5 truncate text-[12px] text-text-secondary">{[card.section, specLine(card)].filter(Boolean).join(" · ")}</p>
        </div>
        {card.state !== "pending" && (
          <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold", card.state === "registered" ? "bg-primary-soft text-primary" : "bg-neutral-100 text-neutral-500")}>
            {card.state === "registered" ? "등록됨" : "건너뜀"}
          </span>
        )}
      </div>
      <div className="mt-2 max-h-[280px] overflow-auto">
        <AssetBlockView block={card.block} caption={false} />
      </div>
      {card.state === "pending" && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[13px] font-medium text-text-primary">등록할까요?</span>
          <ScopePick value={scope} onChange={setScope} />
          <button type="button" disabled={busy} onClick={() => void run({ action: "register", scope })} className="flex h-8 cursor-pointer items-center gap-1 rounded-lg bg-primary px-3 text-[12px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
            {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Check className="size-3.5" aria-hidden />}
            등록
          </button>
          <button type="button" disabled={busy} onClick={() => setEditing(true)} className="h-8 cursor-pointer rounded-lg bg-neutral-100 px-3 text-[12px] font-semibold text-neutral-700 hover:bg-neutral-200 disabled:opacity-50">
            고쳐서 등록
          </button>
          <button type="button" disabled={busy} onClick={() => void run({ action: "skip" })} className="h-8 cursor-pointer rounded-lg px-2.5 text-[12px] font-medium text-text-secondary hover:bg-neutral-100 disabled:opacity-50">
            건너뛰기
          </button>
        </div>
      )}
      {editing && (
        <TemplateDialog
          heading="고쳐서 등록"
          table={{ title: card.title, templateId: null, spec: { name: card.spec.name, subject: card.spec.subject, orientation: card.spec.orientation, itemsOpen: card.spec.itemsOpen }, items: card.spec.items, subjects: card.sampleRows.map((label) => ({ label })) }}
          onClose={() => setEditing(false)}
          onSubmit={async ({ name, scope: sc, spec }) => {
            // 차트 양식은 고친 열 이름으로 계열을 다시 잇는다
            const chart = card.spec.chart ? { ...card.spec.chart, seriesLabels: (spec.items ?? []).filter((i) => !i.hidden && i.type !== "text").map((i) => i.label) } : undefined;
            await run({ action: "register", name, scope: sc, spec: { ...spec, ...(chart ? { chart } : {}) } });
          }}
        />
      )}
    </div>
  );
}

function FormatCard({ box, onFormat }: { box: ImportBox; onFormat: (body: ImportFormatBody) => Promise<unknown> }) {
  const fmt = box.format!;
  const [name, setName] = useState(fmt.name);
  const [scope, setScope] = useState<TemplateScope>("user");
  const [busy, setBusy] = useState(false);
  const byN = new Map(box.items.map((c) => [c.n, c]));
  const done = fmt.state === "registered";

  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-4">
      <div className="flex items-center gap-2.5">
        <LayoutTemplate className="size-5 shrink-0 text-primary" aria-hidden />
        {done ? <p className="flex-1 truncate text-[14px] font-semibold text-text-primary">{fmt.name}</p> : <input value={name} onChange={(e) => setName(e.target.value)} aria-label="양식 이름" className="h-8 min-w-0 flex-1 rounded-lg bg-neutral-100 px-2.5 text-[14px] font-semibold outline-none focus:bg-white focus:ring-2 focus:ring-primary/30" />}
        <span className="shrink-0 text-[12px] text-text-secondary">리포트 양식</span>
        {done && <span className="shrink-0 rounded-full bg-primary-soft px-2 py-0.5 text-[11px] font-semibold text-primary">등록됨</span>}
      </div>
      <ol className="mt-3 flex flex-col gap-1.5">
        {fmt.sections.map((s, i) => (
          <li key={`${s.title}${i}`} className={cn("rounded-xl bg-neutral-50 px-3 py-2", s.level > 1 && "ml-4")}>
            <p className="text-[13px] font-semibold text-text-primary">{s.title}</p>
            {s.guide && <p className="mt-0.5 line-clamp-2 text-[12px] text-text-secondary">{s.guide}</p>}
            {(s.assets.length > 0 || s.figures.length > 0) && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {s.assets.map((n) => {
                  const c = byN.get(n);
                  if (!c) return null;
                  const Icon = c.kind === "chart" ? BarChart3 : Table2;
                  return (
                    <span key={n} className={cn("flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]", c.state === "skipped" ? "bg-neutral-100 text-neutral-400 line-through" : "bg-primary-soft text-primary")}>
                      <Icon className="size-3" aria-hidden />
                      {c.title}
                    </span>
                  );
                })}
                {s.figures.map((f, j) => (
                  <span key={`f${j}`} className="rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] text-neutral-600">
                    그림 자리 · {f}
                  </span>
                ))}
              </div>
            )}
          </li>
        ))}
      </ol>
      {!done && (
        <div className="mt-3 flex items-center justify-end gap-1.5">
          <ScopePick value={scope} onChange={setScope} />
          <button
            type="button"
            disabled={busy || !name.trim()}
            onClick={async () => {
              setBusy(true);
              await onFormat({ name: name.trim(), scope });
              setBusy(false);
            }}
            className="flex h-8 cursor-pointer items-center gap-1 rounded-lg bg-primary px-3 text-[12px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
          >
            {busy && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
            리포트 양식으로 한꺼번에 등록
          </button>
        </div>
      )}
    </div>
  );
}

export function ImportCardList({ box, onItem, onFormat }: { box: ImportBox; onItem: (n: number, body: ImportItemBody) => Promise<unknown>; onFormat: (body: ImportFormatBody) => Promise<unknown> }) {
  return (
    <div className="flex flex-col gap-3">
      {box.items.map((c) => (
        <ItemCard key={c.n} card={c} onItem={onItem} />
      ))}
      {box.format && <FormatCard box={box} onFormat={onFormat} />}
    </div>
  );
}

export function ImportCards({ msgId, box }: { msgId: string; box: ImportBox }) {
  const actions = useReportActions();
  return <ImportCardList box={box} onItem={(n, body) => actions.importAction(msgId, n, body)} onFormat={(body) => actions.registerFormat(msgId, body)} />;
}
