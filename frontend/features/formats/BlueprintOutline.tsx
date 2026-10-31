"use client";

/**
 * 양식 2.0 틀 — 문서 구조 고치기와 표·차트 미리보기(BE templates_import/blueprint_edit.py).
 * 구조 = 표지·요약(고정) → 장(큰 제목) → 소주제(하위 카테고리) → 소주제마다 표·차트 자리 → 부록(재무표)·고지(고정).
 * 장·소주제는 더하기·이름·안내·순서·빼기, 표·차트 자리는 틀의 표·차트 양식에서 고른다. 소제목은 문서를 쓸 때 회사마다 주장 한 줄로 정한다(여기 이름은 자리 이름).
 * 미리보기 = 샘플 값으로 채운 블록(문서 화면과 같은 TableBlockView·ChartBlockView) — 값은 미리보기에만, 문서는 자료로 채운다.
 */
import { ArrowDown, ArrowUp, BarChart3, ImageIcon, Plus, Table2, Trash2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { ChartBlockView, TableBlockView } from "../report/components/report/FormatBlock";
import type { ChartBlock, FigureSlotBlock, TableBlock } from "../report/types";
import type { Blueprint, BlueprintForm, BlueprintSubtopic, OutlineChapter } from "./types";

const field = "rounded-lg bg-neutral-100 px-2.5 text-[13px] outline-none focus:bg-white focus:ring-2 focus:ring-primary/30 disabled:bg-transparent disabled:px-0";
type Preview = TableBlock | ChartBlock | FigureSlotBlock;

/** 틀의 장 → 화면에서 고치는 모양 */
export function chaptersOf(bp: Blueprint | null | undefined): OutlineChapter[] {
  return (bp?.parts ?? [])
    .filter((p) => p.role === "chapter")
    .map((p) => ({ id: p.id, title: p.title, guide: p.guide ?? "", subtopics: (p.subtopics ?? []).map((s) => ({ ...s, guide: s.guide ?? "", blocks: s.blocks ?? [] })) }));
}

function formIcon(f: BlueprintForm | undefined) {
  return f?.kind === "table" ? Table2 : f?.chart ? BarChart3 : ImageIcon;
}

function move<T>(xs: T[], i: number, d: -1 | 1): T[] {
  const j = i + d;
  if (j < 0 || j >= xs.length) return xs;
  const next = [...xs];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

function IconBtn({ label, onClick, disabled, danger, children }: { label: string; onClick: () => void; disabled?: boolean; danger?: boolean; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} disabled={disabled} onClick={onClick} className={cn("cursor-pointer rounded-md p-1 text-neutral-400 disabled:opacity-30", danger ? "hover:bg-red-50 hover:text-red-600" : "hover:bg-neutral-100 hover:text-neutral-700")}>
      {children}
    </button>
  );
}

/** 표·차트 자리 칩 + 더하기 */
function Slots({ bp, ids, ro, previews, onChange, onShow }: { bp: Blueprint; ids: string[]; ro: boolean; previews: Record<string, Preview>; onChange: (ids: string[]) => void; onShow: (id: string) => void }) {
  const titleOf = (id: string) => previews[id]?.title || bp.forms[id]?.title || id;
  const choices = Object.values(bp.forms).filter((f) => f.kind !== "note" && !ids.includes(f.id));
  if (ro && !ids.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      {ids.map((id) => {
        const Icon = formIcon(bp.forms[id]);
        return (
          <span key={id} className="flex items-center rounded-full bg-primary-soft text-[12px] text-primary">
            <button type="button" onClick={() => onShow(id)} title="미리보기" className="flex cursor-pointer items-center gap-1 py-1 pr-1 pl-2.5">
              <Icon className="size-3.5" aria-hidden />
              <span className="max-w-[220px] truncate">{titleOf(id)}</span>
            </button>
            {!ro && (
              <button type="button" aria-label="자리 빼기" onClick={() => onChange(ids.filter((x) => x !== id))} className="mr-1 cursor-pointer rounded-full p-0.5 opacity-70 hover:opacity-100">
                <X className="size-3" aria-hidden />
              </button>
            )}
          </span>
        );
      })}
      {!ro && choices.length > 0 && (
        <select value="" onChange={(e) => e.target.value && onChange([...ids, e.target.value])} aria-label="표·차트 자리 더하기" className="h-7 max-w-[200px] cursor-pointer rounded-full bg-neutral-100 px-2 text-[12px] text-neutral-600 outline-none hover:bg-neutral-200">
          <option value="">+ 표·차트</option>
          {choices.map((f) => (
            <option key={f.id} value={f.id}>
              {f.kind === "table" ? "표" : f.chart ? "차트" : "그림"} · {titleOf(f.id)}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

export function OutlineEditor({ bp, chapters, setChapters, ro, previews, onShow }: { bp: Blueprint; chapters: OutlineChapter[]; setChapters: (c: OutlineChapter[]) => void; ro: boolean; previews: Record<string, Preview>; onShow: (id: string) => void }) {
  const front = bp.parts.filter((p) => p.role === "cover" || p.role === "summary");
  const back = bp.parts.filter((p) => p.role === "appendix");
  const setCh = (i: number, patch: Partial<OutlineChapter>) => setChapters(chapters.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const setSub = (i: number, k: number, patch: Partial<BlueprintSubtopic>) => setCh(i, { subtopics: chapters[i].subtopics.map((s, j) => (j === k ? { ...s, ...patch } : s)) });
  const fixed = (label: string, ids: string[]) => (
    <div className="rounded-2xl bg-white/70 p-3.5 ring-1 ring-neutral-200">
      <p className="text-[13px] font-semibold text-neutral-500">{label}</p>
      <Slots bp={bp} ids={ids} ro previews={previews} onChange={() => undefined} onShow={onShow} />
    </div>
  );
  return (
    <div className="flex flex-col gap-2.5">
      {front.map((p) =>
        p.role === "cover" ? (
          <div key={p.id}>{fixed("표지 — 대상·제목·작성일·체크포인트(요약 주장)", [])}</div>
        ) : (
          <div key={p.id}>{fixed(`요약 쪽 — 주장 ${p.claims ?? 3}개 + 표 · 옆 칸`, [...(p.blocks ?? []), ...(p.sidebar ?? [])])}</div>
        ),
      )}
      {chapters.map((c, i) => (
        <div key={c.id ?? `new${i}`} className="rounded-2xl bg-white p-3.5">
          <div className="flex items-center gap-2">
            <span className="flex h-7 shrink-0 items-center rounded-md bg-[#C00000] px-2.5 text-[12px] font-bold text-white">{i + 1}장</span>
            <input value={c.title} disabled={ro} onChange={(e) => setCh(i, { title: e.target.value })} aria-label="장 이름" placeholder="장 이름(큰 제목)" className={cn(field, "h-8 min-w-0 flex-1 text-[15px] font-bold text-text-primary")} />
            {!ro && (
              <span className="flex shrink-0 items-center">
                <IconBtn label="장 위로" disabled={i === 0} onClick={() => setChapters(move(chapters, i, -1))}>
                  <ArrowUp className="size-4" aria-hidden />
                </IconBtn>
                <IconBtn label="장 아래로" disabled={i === chapters.length - 1} onClick={() => setChapters(move(chapters, i, 1))}>
                  <ArrowDown className="size-4" aria-hidden />
                </IconBtn>
                <IconBtn label="장 빼기" danger disabled={chapters.length <= 1} onClick={() => setChapters(chapters.filter((_, j) => j !== i))}>
                  <Trash2 className="size-4" aria-hidden />
                </IconBtn>
              </span>
            )}
          </div>
          {ro ? (
            c.guide && <p className="mt-1.5 text-[13px] leading-5 text-text-secondary">{c.guide}</p>
          ) : (
            <textarea value={c.guide} onChange={(e) => setCh(i, { guide: e.target.value })} rows={1} placeholder="이 장에서 다루는 것(작성 안내)" aria-label="장 안내" className={cn(field, "mt-2 w-full resize-y py-1.5 leading-5")} />
          )}
          <div className="mt-2.5 flex flex-col gap-2 border-l-2 border-neutral-200 pl-3">
            {c.subtopics.map((s, k) => (
              <div key={k} className="rounded-xl bg-neutral-50 p-2.5">
                <div className="flex items-center gap-2">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded bg-[#C00000]/90 text-[11px] font-bold text-white">{k + 1}</span>
                  <input value={s.title} disabled={ro} onChange={(e) => setSub(i, k, { title: e.target.value })} aria-label="소주제 이름" placeholder="소주제(하위 카테고리) 이름" className={cn(field, "h-7 min-w-0 flex-1 bg-white font-semibold text-text-primary")} />
                  {!ro && (
                    <span className="flex shrink-0 items-center">
                      <IconBtn label="소주제 위로" disabled={k === 0} onClick={() => setCh(i, { subtopics: move(c.subtopics, k, -1) })}>
                        <ArrowUp className="size-3.5" aria-hidden />
                      </IconBtn>
                      <IconBtn label="소주제 아래로" disabled={k === c.subtopics.length - 1} onClick={() => setCh(i, { subtopics: move(c.subtopics, k, 1) })}>
                        <ArrowDown className="size-3.5" aria-hidden />
                      </IconBtn>
                      <IconBtn label="소주제 빼기" danger disabled={c.subtopics.length <= 1} onClick={() => setCh(i, { subtopics: c.subtopics.filter((_, j) => j !== k) })}>
                        <Trash2 className="size-3.5" aria-hidden />
                      </IconBtn>
                    </span>
                  )}
                </div>
                {ro ? (
                  s.guide && <p className="mt-1 text-[12.5px] leading-5 text-text-secondary">{s.guide}</p>
                ) : (
                  <textarea value={s.guide} onChange={(e) => setSub(i, k, { guide: e.target.value })} rows={1} placeholder="무엇을 어떤 근거로 쓰는지" aria-label="소주제 안내" className={cn(field, "mt-1.5 w-full resize-y bg-white py-1.5 leading-5")} />
                )}
                {s.example && <p className="mt-1 text-[11px] text-neutral-400">샘플 소제목: {s.example}</p>}
                <Slots bp={bp} ids={s.blocks} ro={ro} previews={previews} onChange={(ids) => setSub(i, k, { blocks: ids })} onShow={onShow} />
              </div>
            ))}
            {!ro && (
              <button type="button" onClick={() => setCh(i, { subtopics: [...c.subtopics, { title: "새 소주제", guide: "", blocks: [] }] })} className="flex w-fit cursor-pointer items-center gap-1 text-[12px] text-neutral-500 hover:text-primary">
                <Plus className="size-3.5" aria-hidden />
                소주제 더하기
              </button>
            )}
          </div>
        </div>
      ))}
      {!ro && (
        <button type="button" onClick={() => setChapters([...chapters, { title: "새 장", guide: "", subtopics: [{ title: "새 소주제", guide: "", blocks: [] }] }])} className="flex cursor-pointer items-center justify-center gap-1 rounded-2xl border border-dashed border-neutral-300 py-2.5 text-[13px] text-neutral-500 hover:border-primary hover:text-primary">
          <Plus className="size-4" aria-hidden />장 더하기
        </button>
      )}
      {back.map((p) => (
        <div key={p.id}>{fixed(`${p.title || "부록"} — 표만`, p.blocks ?? [])}</div>
      ))}
    </div>
  );
}

/** 표·차트 양식 미리보기 — 쓰는 자리별로(요약 쪽 · 장 › 소주제 · 부록 · 쓰는 곳 없음), 샘플 값으로 채운 블록 */
export function BlueprintAssets({ bp, chapters, previews, selId, onSelect }: { bp: Blueprint; chapters: OutlineChapter[]; previews: Record<string, Preview>; selId: string | null; onSelect: (id: string) => void }) {
  const groups: { label: string; ids: string[] }[] = [];
  const summary = bp.parts.find((p) => p.role === "summary");
  if (summary) groups.push({ label: "요약 쪽", ids: [...(summary.blocks ?? []), ...(summary.sidebar ?? [])] });
  chapters.forEach((c) => c.subtopics.forEach((s) => s.blocks.length && groups.push({ label: `${c.title} › ${s.title}`, ids: s.blocks })));
  bp.parts.filter((p) => p.role === "appendix").forEach((p) => groups.push({ label: p.title || "부록", ids: p.blocks ?? [] }));
  const used = new Set(groups.flatMap((g) => g.ids));
  const rest = Object.keys(bp.forms).filter((id) => !used.has(id) && bp.forms[id].kind !== "note");
  if (rest.length) groups.push({ label: "쓰는 자리 없음(소주제에 더할 수 있다)", ids: rest });
  return (
    <div className="flex flex-col gap-5">
      <p className="text-[12px] text-text-secondary">샘플 값으로 채운 미리보기입니다 — 문서를 쓰면 같은 모양으로 자료 값이 들어갑니다. 사진·그림 자리는 자료를 넣을 빈 칸으로 남습니다.</p>
      {groups.map((g) => (
        <section key={g.label} className="flex flex-col gap-2">
          <p className="px-1 text-[12px] font-semibold text-neutral-500">{g.label}</p>
          {g.ids.map((id) => {
            const b = previews[id];
            if (!b) return null;
            const on = id === selId;
            const f = bp.forms[id];
            // 원본 자리 — 쪽과 샘플 제목(일반 제목으로 바꾼 것이면). 오른쪽 '원본'에 같은 자리를 잘라 보인다
            const origin = [f?.page ? `p.${f.page}` : "", f?.sampleTitle && f.sampleTitle !== b.title ? f.sampleTitle : ""].filter(Boolean).join(" · ");
            return (
              <div
                key={`${g.label}-${id}`}
                role="button"
                tabIndex={0}
                onClick={() => onSelect(id)}
                onKeyDown={(e) => e.key === "Enter" && onSelect(id)}
                className={cn("cursor-pointer rounded-2xl bg-white p-4 transition-shadow", on ? "ring-2 ring-primary" : "ring-1 ring-neutral-200 hover:ring-neutral-300")}
              >
                {b.kind === "table" ? (
                  <TableBlockView block={b} />
                ) : b.kind === "chart" ? (
                  <ChartBlockView block={b} />
                ) : (
                  <div>
                    <p className="mb-1.5 text-[13px] font-bold text-text-primary">{b.title}</p>
                    <div className="flex h-20 items-center justify-center rounded-lg border border-dashed border-neutral-300 text-[12px] text-neutral-400">그림 자리 — 사진·그림은 자료에서 넣습니다</div>
                  </div>
                )}
                {origin && <p className="mt-2 truncate border-t border-neutral-100 pt-1.5 text-[11px] text-neutral-400">원본 {origin}</p>}
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}
