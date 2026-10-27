"use client";

/**
 * 리포트 뷰 — BE 가 조립한 ReportView 를 그대로 보여 준다(OP-FE PaperView 이식): 제목 → 부제 → 섹션 → 참고 자료.
 * 섹션 단위 손질(이름 바꾸기·순서·삭제·본문 직접 편집)은 여기서 한다(모두 PATCH 한 번).
 * 본문 편집기에서는 출처 토큰을 `[#n]` 으로 보여 주고 저장할 때 원래 토큰으로 되돌린다(지운 표지는 출처도 빠진다).
 */
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useAtomValue } from "jotai";
import { ArrowDown, ArrowUp, Check, History, PencilLine, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { FEATURES } from "../../../workspace/features";
import { canChatAtom, focusStepAtom, numberFocusAtom, numbersAtom, reportAtom, sessionAtom, versionsAtom } from "../../atoms";
import type { NumberSpan } from "../../types";
import { useReportActions } from "../../hooks/useReportStudio";
import { BlockView } from "./BlockView";
import { ReadinessChip } from "./ReadinessChip";

const TOKEN = /\[@[0-9a-f]{16}#[A-Za-z0-9_-]+\]/g;

function toEditable(content: string): { text: string; map: Map<string, string> } {
  const map = new Map<string, string>();
  const byToken = new Map<string, string>();
  const text = content.replace(TOKEN, (tok) => {
    let key = byToken.get(tok);
    if (!key) {
      key = `[#${byToken.size + 1}]`;
      byToken.set(tok, key);
      map.set(key, tok);
    }
    return key;
  });
  return { text, map };
}

function fromEditable(text: string, map: Map<string, string>): string {
  return text.replace(/\[#\d+\]/g, (k) => map.get(k) ?? "");
}

export const ReportView = memo(function ReportView() {
  const actions = useReportActions();
  const report = useAtomValue(reportAtom);
  const session = useAtomValue(sessionAtom);
  const focusStep = useAtomValue(focusStepAtom);
  const numbers = useAtomValue(numbersAtom);
  const numberFocus = useAtomValue(numberFocusAtom);
  const containerRef = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState<{ step: string; text: string; map: Map<string, string> } | null>(null);
  const [renaming, setRenaming] = useState<{ step: string; title: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const sections = useMemo(() => session?.sections ?? [], [session]);
  const blocks = report?.blocks ?? [];
  const spansByBlock = useMemo(() => {
    const out = new Map<number, NumberSpan[]>();
    for (const s of numbers?.spans ?? []) out.set(s.b, [...(out.get(s.b) ?? []), s]);
    return out;
  }, [numbers]);

  // 숫자 출처 탭에서 고른 숫자로 본문을 옮긴다
  useEffect(() => {
    if (!numberFocus) return;
    containerRef.current?.querySelector<HTMLElement>(`[data-num="${numberFocus.key}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [numberFocus]);

  useEffect(() => {
    if (!focusStep) return;
    containerRef.current?.querySelector<HTMLElement>(`[data-step="${focusStep}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focusStep, blocks]);

  const saveEdit = async () => {
    if (!editing || saving) return;
    setSaving(true);
    try {
      const content = fromEditable(editing.text, editing.map);
      if (await actions.patchSection(editing.step, content.trim() ? content : null)) {
        setEditing(null);
        toast.success("저장했습니다.", { position: "top-center" });
      }
    } finally {
      setSaving(false);
    }
  };

  const commitRename = async () => {
    if (!renaming || saving) return;
    if (!renaming.title.trim()) return setRenaming(null);
    setSaving(true);
    try {
      if (await actions.rename(renaming.step, renaming.title)) setRenaming(null);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-neutral-200 px-4">
        <div className="flex min-w-0 items-center gap-2">
          <h2 className="text-sm font-semibold text-text-primary">문서</h2>
          {report && (
            <span className="truncate text-xs text-text-secondary tabular-nums">
              섹션 {report.stats.written}/{report.stats.sections} · {report.stats.chars.toLocaleString()}자 · 출처 {report.stats.citations}곳
            </span>
          )}
        </div>
        <span className="flex shrink-0 items-center gap-1.5">
          <VersionsMenu />
          {FEATURES.reviewRequest && <ReadinessChip />}
        </span>
      </header>

      <div ref={containerRef} className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-background-gray px-4 py-5">
        <article className="mx-auto max-w-[46rem] rounded-xl border border-neutral-200 bg-white px-8 py-8">
          <h1 className="text-xl leading-snug font-bold text-text-primary">{report?.title}</h1>
          {report?.subtitle && <p className="mt-1.5 text-xs text-text-secondary">{report.subtitle}</p>}

          {blocks.map((b, i) => {
            const section = sections.find((s) => s.step === b.step);
            if (editing && b.step === editing.step && b.kind !== "heading") return null;
            return (
              <div key={i} className="group">
                <BlockView block={b} focused={b.step === focusStep} nums={spansByBlock.get(i) ?? []} activeKey={numberFocus?.key} />
                {b.kind === "heading" && section && (
                  <>
                    {renaming?.step === section.step ? (
                      <div className="mt-1.5 flex items-center gap-1.5">
                        <input
                          autoFocus
                          className="h-7 min-w-0 flex-1 rounded-md border border-neutral-200 bg-white px-2 text-xs"
                          value={renaming.title}
                          disabled={saving}
                          onChange={(e) => setRenaming({ step: section.step, title: e.target.value })}
                          onKeyDown={(e) => {
                            if (e.nativeEvent.isComposing) return;
                            if (e.key === "Enter") void commitRename();
                            if (e.key === "Escape") setRenaming(null);
                          }}
                        />
                        <IconButton label="저장" onClick={() => void commitRename()}>
                          <Check className="size-3.5" aria-hidden />
                        </IconButton>
                        <IconButton label="취소" onClick={() => setRenaming(null)}>
                          <X className="size-3.5" aria-hidden />
                        </IconButton>
                      </div>
                    ) : (
                      <div className="mt-1 flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                        <IconButton label="이름 바꾸기" onClick={() => setRenaming({ step: section.step, title: section.title })}>
                          <PencilLine className="size-3.5" aria-hidden />
                        </IconButton>
                        <IconButton label="위로" disabled={sections[0]?.step === section.step} onClick={() => void actions.reorder(section.step, "up")}>
                          <ArrowUp className="size-3.5" aria-hidden />
                        </IconButton>
                        <IconButton label="아래로" disabled={sections[sections.length - 1]?.step === section.step} onClick={() => void actions.reorder(section.step, "down")}>
                          <ArrowDown className="size-3.5" aria-hidden />
                        </IconButton>
                        {section.content && (
                          <IconButton label="본문 편집" onClick={() => setEditing({ step: section.step, ...toEditable(section.content ?? "") })}>
                            <span className="text-xs">편집</span>
                          </IconButton>
                        )}
                        <IconButton label="섹션 삭제" destructive onClick={() => window.confirm("이 섹션을 지울까요?") && void actions.remove(section.step)}>
                          <Trash2 className="size-3.5" aria-hidden />
                        </IconButton>
                      </div>
                    )}
                    {editing?.step === section.step && (
                      <div className="mt-2 flex flex-col gap-2">
                        <textarea
                          autoFocus
                          rows={12}
                          disabled={saving}
                          className="thin-scrollbar w-full rounded-lg border border-neutral-200 bg-white p-3 text-sm leading-7 text-text-primary"
                          value={editing.text}
                          onChange={(e) => setEditing({ ...editing, text: e.target.value })}
                        />
                        <p className="text-[11px] text-text-secondary">[#n] 은 출처 표지입니다 — 지우면 그 출처도 빠집니다.</p>
                        <div className="flex items-center justify-end gap-1.5">
                          <button type="button" disabled={saving} onClick={() => setEditing(null)} className="cursor-pointer rounded-md border border-neutral-200 px-2.5 py-1 text-xs text-text-secondary hover:bg-neutral-100">
                            취소
                          </button>
                          <button type="button" disabled={saving} onClick={() => void saveEdit()} className="cursor-pointer rounded-md bg-primary px-2.5 py-1 text-xs text-white hover:bg-primary-hover">
                            저장
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          })}

          {(report?.sources.length ?? 0) > 0 && (
            <section className="mt-10 border-t border-neutral-200 pt-4">
              <h2 className="text-sm font-bold text-text-primary">참고 자료</h2>
              <ol className="mt-2 flex flex-col gap-1">
                {report!.sources.map((s) => (
                  <li key={s.docId}>
                    <button
                      type="button"
                      onClick={() => actions.openDocument(s.docId)}
                      className={cn("cursor-pointer text-left text-xs leading-6 text-text-primary hover:text-primary", s.missing && "text-text-secondary line-through")}
                    >
                      [{s.n}] {s.label}
                      {[s.issuer, s.docType, s.date].filter(Boolean).length > 0 && <span className="text-text-secondary"> ({[s.issuer, s.docType, s.date].filter(Boolean).join(", ")})</span>}
                    </button>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </article>
      </div>
    </div>
  );
});

/** 문서 판 — 리서치로 바꿀 때 남긴 '중간 저장'·직접 남긴 판·되돌리기 전. 되돌리면 지금 상태도 판으로 남는다 */
function VersionsMenu() {
  const actions = useReportActions();
  const versions = useAtomValue(versionsAtom);
  const canChat = useAtomValue(canChatAtom);
  const report = useAtomValue(reportAtom);
  const [open, setOpen] = useState(false);
  const when = (iso: string) => new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
  if (!canChat) return null;
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex h-7 cursor-pointer items-center gap-1 rounded-md px-2 text-xs text-text-secondary hover:bg-neutral-100 hover:text-text-primary">
        <History className="size-3.5" aria-hidden />판 {versions.length}
      </button>
      {open && (
        <div className="absolute top-full right-0 z-30 mt-1 w-64 rounded-2xl bg-white p-1.5 shadow-[0_8px_24px_rgba(0,27,55,0.14)]" onMouseLeave={() => setOpen(false)}>
          <button
            type="button"
            disabled={!report?.stats.written}
            onClick={() => (setOpen(false), void actions.saveVersion())}
            className="flex w-full cursor-pointer rounded-xl px-3 py-2 text-left text-[13px] font-semibold text-primary hover:bg-neutral-100 disabled:cursor-default disabled:opacity-40"
          >
            지금 상태를 판으로 남기기
          </button>
          {versions.map((v) => (
            <div key={v.id} className="flex items-center gap-2 rounded-xl px-3 py-1.5 hover:bg-neutral-50">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] text-text-primary">{v.label}</span>
                <span className="block text-[11px] text-text-secondary">
                  {when(v.at)} · {v.written}섹션
                </span>
              </span>
              <button
                type="button"
                onClick={() => window.confirm(`'${v.label}' 판으로 되돌릴까요? 지금 상태는 '되돌리기 전' 판으로 남습니다.`) && (setOpen(false), void actions.restoreVersion(v.id))}
                className="shrink-0 cursor-pointer rounded-md px-2 py-1 text-[11px] font-medium text-text-secondary hover:bg-neutral-100 hover:text-primary"
              >
                되돌리기
              </button>
            </div>
          ))}
          {versions.length === 0 && <p className="px-3 py-2 text-[12px] text-text-secondary">남긴 판이 없습니다</p>}
        </div>
      )}
    </div>
  );
}

function IconButton({ label, onClick, disabled, destructive, children }: { label: string; onClick: () => void; disabled?: boolean; destructive?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={cn("cursor-pointer rounded p-1 text-text-secondary transition-colors hover:bg-neutral-100 hover:text-text-primary disabled:opacity-30", destructive && "hover:text-red-600")}
    >
      {children}
    </button>
  );
}
