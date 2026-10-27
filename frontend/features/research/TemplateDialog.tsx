"use client";

/**
 * 양식으로 저장 — 지금 표의 열을 고쳐 양식으로. 행은 '매번 정함'(기본) 또는 '지금 행 고정', 방향(행·열), 범위(나만·워크스페이스).
 * 계산 열 식은 앞 열 이름으로 쓴다(ratio(영업이익, 매출액) · growth(새, 옛) · diff(a, b)). 서버가 열 이름을 열 key 로 바꾸고 검사한다.
 */
import { useState } from "react";
import { Plus, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError } from "../report/api";
import { useWorkspace } from "../workspace/context";
import { createTemplate } from "./api";
import type { ItemType, Orientation, ResearchTable, TemplateItem, TemplateScope, TemplateSpec } from "./types";

const TYPES: { id: ItemType; label: string }[] = [
  { id: "number", label: "숫자" },
  { id: "text", label: "글" },
  { id: "calc", label: "계산" },
];

const input = "h-9 rounded-lg bg-neutral-100 px-2.5 text-[13px] outline-none focus:bg-white focus:ring-2 focus:ring-primary/30";

function Seg<T extends string>({ value, options, onChange, disabled }: { value: T; options: { id: T; label: string; disabled?: boolean }[]; onChange: (v: T) => void; disabled?: boolean }) {
  return (
    <div className="flex rounded-xl bg-neutral-100 p-1">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          disabled={disabled || o.disabled}
          onClick={() => onChange(o.id)}
          className={cn(
            "flex-1 cursor-pointer rounded-lg px-3 py-1.5 text-[13px] font-semibold transition-colors disabled:cursor-default disabled:opacity-40",
            value === o.id ? "bg-white text-text-primary shadow-sm" : "text-neutral-500 hover:text-neutral-700",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** 계산식 표시용 — 열 key 를 열 이름으로(저장할 때는 서버가 다시 key 로 바꾼다) */
function readableFormula(formula: string, items: TemplateItem[]): string {
  let out = formula;
  for (const it of [...items].sort((a, b) => b.key.length - a.key.length)) out = out.replace(new RegExp(`\\b${it.key}\\b`, "g"), it.label);
  return out;
}

/** onSubmit 을 주면 저장 대신 그것을 부른다(양식 샘플 카드의 '고쳐서 등록'). edit = 저장한 양식 고치기(범위는 그대로, 고정 행이 있으면 지킨다) */
export function TemplateDialog({
  table,
  onClose,
  onSubmit,
  heading = "양식으로 저장",
  edit = false,
}: {
  table: Pick<ResearchTable, "title" | "templateId" | "spec" | "items" | "subjects">;
  onClose: () => void;
  onSubmit?: (b: { name: string; scope: TemplateScope; spec: Partial<TemplateSpec> }) => Promise<void>;
  heading?: string;
  edit?: boolean;
}) {
  const ws = useWorkspace();
  const visible = table.items.filter((i) => !i.hidden);
  const hidden = table.items.filter((i) => i.hidden);
  const [name, setName] = useState(table.spec.name && table.templateId ? `${table.spec.name}` : table.title);
  const [scope, setScope] = useState<TemplateScope>("user");
  const [keepRows, setKeepRows] = useState(edit && table.subjects.length > 0);
  const [orientation, setOrientation] = useState<Orientation>(table.spec.orientation);
  const [subjectLabel, setSubjectLabel] = useState(table.spec.subject.label);
  const [items, setItems] = useState<TemplateItem[]>(
    visible.map((i) => ({
      ...i,
      formula: i.formula ? readableFormula(i.formula, table.items) : undefined,
    })),
  );
  const [busy, setBusy] = useState(false);

  const set = (i: number, patch: Partial<TemplateItem>) => setItems((cur) => cur.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  const save = async () => {
    setBusy(true);
    try {
      const all = [
        ...hidden,
        ...items.map((it) => ({
          ...it,
          metric: it.type === "number" ? it.metric || it.label : undefined,
        })),
      ];
      const spec: Partial<TemplateSpec> = {
        name: name.trim() || table.title,
        subject: {
          kind: table.spec.subject.kind,
          label: subjectLabel.trim() || table.spec.subject.label,
        },
        rows: keepRows ? table.subjects : null,
        items: all,
        itemsOpen: false,
        orientation,
        inputs: [],
      };
      if (onSubmit) {
        await onSubmit({ name: name.trim() || table.title, scope, spec });
        onClose();
        return;
      }
      const t = await createTemplate(ws.workspaceId, { name: name.trim() || table.title, scope, spec });
      toast.success(`양식 '${t.name}' 을 저장했습니다.`, {
        position: "top-center",
      });
      onClose();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "저장하지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="thin-scrollbar max-h-[88vh] w-full max-w-[640px] overflow-y-auto rounded-[24px] bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <h2 className="flex-1 text-[20px] font-bold tracking-tight text-text-primary">{heading}</h2>
          <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>

        <div className="mt-5 flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-semibold text-neutral-600">이름</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className="h-11 rounded-xl bg-neutral-100 px-4 text-[15px] outline-none focus:bg-white focus:ring-2 focus:ring-primary/30" />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <span className="text-[13px] font-semibold text-neutral-600">행</span>
              <Seg
                value={keepRows ? "keep" : "open"}
                onChange={(v) => setKeepRows(v === "keep")}
                options={[
                  { id: "open", label: "매번 정함" },
                  { id: "keep", label: edit ? "행 고정" : "지금 행 고정", disabled: table.subjects.length === 0 },
                ]}
              />
            </div>
            <div className={cn("flex flex-col gap-1.5", edit && "hidden")}>
              <span className="text-[13px] font-semibold text-neutral-600">범위</span>
              <Seg
                value={scope}
                onChange={setScope}
                options={[
                  { id: "user", label: "나만" },
                  {
                    id: "workspace",
                    label: "워크스페이스",
                    disabled: !ws.can("editor"),
                  },
                ]}
              />
            </div>
          </div>

          {keepRows ? (
            <p className="rounded-xl bg-neutral-50 px-3.5 py-2.5 text-[13px] text-text-secondary">{table.subjects.map((s) => s.label).join(" · ")}</p>
          ) : (
            <label className="flex items-center gap-3">
              <span className="w-[72px] shrink-0 text-[13px] font-semibold text-neutral-600">행 이름</span>
              <input value={subjectLabel} onChange={(e) => setSubjectLabel(e.target.value)} className={cn(input, "w-40")} />
            </label>
          )}

          <div className="flex items-center gap-3">
            <span className="w-[72px] shrink-0 text-[13px] font-semibold text-neutral-600">방향</span>
            <div className="w-64">
              <Seg
                value={orientation}
                onChange={setOrientation}
                options={[
                  {
                    id: "subjects_as_rows",
                    label: `행 = ${subjectLabel || "행"}`,
                  },
                  {
                    id: "items_as_rows",
                    label: `열 = ${subjectLabel || "행"}`,
                  },
                ]}
              />
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-semibold text-neutral-600">열</span>
            {items.map((it, i) => (
              <div key={`${it.key}${i}`} className="rounded-2xl bg-neutral-50 p-3">
                <div className="flex items-center gap-2">
                  <input value={it.label} onChange={(e) => set(i, { label: e.target.value })} placeholder="열 이름" className={cn(input, "min-w-0 flex-1 bg-white")} />
                  <select value={it.type} onChange={(e) => set(i, { type: e.target.value as ItemType })} className={cn(input, "w-20 bg-white")}>
                    {TYPES.map((x) => (
                      <option key={x.id} value={x.id}>
                        {x.label}
                      </option>
                    ))}
                  </select>
                  {it.type !== "text" && <input value={it.unit ?? ""} onChange={(e) => set(i, { unit: e.target.value || undefined })} placeholder="단위" className={cn(input, "w-20 bg-white")} />}
                  <button
                    type="button"
                    aria-label="열 빼기"
                    onClick={() => setItems((cur) => cur.filter((_, j) => j !== i))}
                    className="cursor-pointer rounded-lg p-1.5 text-neutral-400 hover:bg-white hover:text-neutral-700"
                  >
                    <X className="size-4" aria-hidden />
                  </button>
                </div>
                {it.type === "calc" && (
                  <input value={it.formula ?? ""} onChange={(e) => set(i, { formula: e.target.value })} placeholder="ratio(영업이익, 매출액)" className={cn(input, "mt-2 w-full bg-white font-mono")} />
                )}
                <input value={it.instruction ?? ""} onChange={(e) => set(i, { instruction: e.target.value || undefined })} placeholder="AI 지침(선택)" className={cn(input, "mt-2 w-full bg-white")} />
              </div>
            ))}
            <button
              type="button"
              disabled={items.length >= 10}
              onClick={() => setItems((cur) => [...cur, { key: "", label: "", type: "number" }])}
              className="flex h-10 cursor-pointer items-center justify-center gap-1.5 rounded-2xl border border-dashed border-neutral-300 text-[13px] font-medium text-neutral-500 hover:border-primary hover:text-primary disabled:opacity-40"
            >
              <Plus className="size-4" aria-hidden />열 더하기
            </button>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="h-10 cursor-pointer rounded-xl bg-neutral-100 px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-200">
            취소
          </button>
          <button
            type="button"
            disabled={busy || !items.some((x) => x.label.trim())}
            onClick={() => void save()}
            className="h-10 cursor-pointer rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40"
          >
            {onSubmit && !edit ? "등록" : "저장"}
          </button>
        </div>
      </div>
    </div>
  );
}
