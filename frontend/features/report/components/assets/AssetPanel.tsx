"use client";

/**
 * 리서치 결과 — 이 작업에서 만든·연 표·차트·메모. 칸·점·출처를 누르면 원문 확인 창에 원본이 강조되어 열린다.
 * AssetCard 하나를 채팅 안(답 아래, FEATURES.panelTabs=false)과 오른쪽 '결과' 탭(AssetPanel, 켜면)이 같이 쓴다.
 * 버튼: 문서에 넣기(표·차트 = 섹션 뒤 복사본, 메모 = 섹션 끝에 글로) · 차트(표에서 막대·꺾은선) · 양식으로 저장(표) · 저장(드라이브 '정리한 데이터') · 내려받기 · 행/열 바꾸기(표).
 * 남이 만든 에셋은 넣기·차트·내려받기만. 메모는 근거 자료가 아니다(메모 속 출처는 원문 그대로).
 */
import { useState } from "react";
import { useAtomValue } from "jotai";
import { ArrowLeftRight, BarChart3, Download, FilePlus2, FolderCheck, FolderPlus, LayoutTemplate, LineChart, Loader2, NotebookPen, Table2 } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { patchTable, tableExportPath } from "../../../research/api";
import { TemplateDialog } from "../../../research/TemplateDialog";
import type { ResearchTable } from "../../../research/types";
import { ApiError, downloadFile } from "../../api";
import { activeTableIdAtom, canChatAtom, hasDocAtom, sessionAtom, tablesAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import { AssetBlockView } from "../report/FormatBlock";

const btn = "flex h-8 cursor-pointer items-center gap-1.5 rounded-lg bg-neutral-100 px-2.5 text-[12px] font-semibold text-neutral-700 transition-colors hover:bg-neutral-200 disabled:cursor-default disabled:opacity-50";

function Menu({ label, icon: Icon, iconOnly, disabled, items }: { label: string; icon: typeof Download; iconOnly?: boolean; disabled?: boolean; items: { key: string; label: string; onClick: () => void }[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button type="button" title={label} aria-label={label} disabled={disabled} onClick={() => setOpen((v) => !v)} className={btn}>
        <Icon className="size-3.5" aria-hidden />
        {!iconOnly && label}
      </button>
      {open && (
        <div className="absolute top-full left-0 z-30 mt-1 max-h-72 w-52 overflow-y-auto rounded-2xl bg-white p-1.5 shadow-[0_8px_24px_rgba(0,27,55,0.14)]" onMouseLeave={() => setOpen(false)}>
          {items.map((it) => (
            <button key={it.key} type="button" onClick={() => (setOpen(false), it.onClick())} className="flex w-full cursor-pointer items-center rounded-xl px-3 py-2 text-left text-[13px] font-medium text-text-primary hover:bg-neutral-100">
              <span className="truncate">{it.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** 'n행 × m열' — 보이는 방향대로(지표가 행인 표는 뒤집어 센다) */
export function shapeOf(t: Pick<ResearchTable, "subjects" | "items" | "spec">): string {
  const s = t.subjects.length;
  const i = t.items.filter((x) => !x.hidden).length;
  return t.spec.orientation === "items_as_rows" ? `${i}행 × ${s}열` : `${s}행 × ${i}열`;
}

/** 칩 아이콘 — 표 / 막대 / 꺾은선 / 메모 */
export function assetIcon(t: Pick<ResearchTable, "kind" | "chart">) {
  return t.kind === "note" ? NotebookPen : t.kind === "chart" ? (t.chart?.type === "line" ? LineChart : BarChart3) : Table2;
}

/** 표·차트·메모 하나 — 제목·버튼·본문. inline = 채팅 답 아래(테두리, 큰 표는 안에서 스크롤) */
export function AssetCard({ t, inline = false }: { t: ResearchTable; inline?: boolean }) {
  const actions = useReportActions();
  const session = useAtomValue(sessionAtom);
  const hasDoc = useAtomValue(hasDocAtom);
  const canChat = useAtomValue(canChatAtom);
  const [busy, setBusy] = useState(false);
  const [templating, setTemplating] = useState(false);

  const run = async (fn: () => Promise<unknown>, fail: string) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : fail, { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  const chart = t.kind === "chart";
  const note = t.kind === "note";
  const sections = session?.sections ?? [];
  const done = t.status === "done";

  return (
    <div className={cn(inline && "rounded-2xl border border-neutral-200 bg-white px-4 py-3")}>
      <h2 className={cn("leading-snug font-bold tracking-tight text-text-primary", inline ? "text-[14px]" : "text-[16px]")}>{t.title}</h2>
      <p className="mt-1 flex flex-wrap items-center gap-x-2 text-[12px] text-text-secondary">
        {t.period && <span>{t.period.label} 기준</span>}
        {note ? (
          <span>메모 · 출처 {t.block.kind === "note" ? t.block.cites.length : 0}</span>
        ) : chart ? (
          t.chart?.sourceTitle && <span className="truncate">원 표: {t.chart.sourceTitle}</span>
        ) : (
          <span>{shapeOf(t)}</span>
        )}
        {!t.mine && <span>{t.createdBy}</span>}
        {t.status === "running" && (
          <span className="flex items-center gap-1 text-primary">
            <Loader2 className="size-3 animate-spin" aria-hidden />
            {t.progress.done ?? 0}/{t.progress.total ?? t.subjects.length}
          </span>
        )}
      </p>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {hasDoc && canChat && (
          <Menu label="문서에 넣기" icon={FilePlus2} disabled={!done || !sections.length} items={sections.map((s) => ({ key: s.step, label: note ? `${s.title} 끝에` : `${s.title} 뒤에`, onClick: () => void actions.insertAsset(t.id, s.step) }))} />
        )}
        {!chart && !note && canChat && (
          <Menu
            label="차트"
            icon={BarChart3}
            disabled={!done || busy}
            items={(["bar", "line"] as const).map((type) => ({ key: type, label: type === "bar" ? "막대 차트" : "꺾은선 차트", onClick: () => void run(() => actions.addChart(t.id, type), "차트를 만들지 못했습니다.") }))}
          />
        )}
        {t.mine && !chart && !note && (
          <button type="button" disabled={t.status === "running"} onClick={() => setTemplating(true)} className={btn}>
            <LayoutTemplate className="size-3.5" aria-hidden />
            양식으로 저장
          </button>
        )}
        {t.mine && (
          <button
            type="button"
            disabled={busy || t.saved || t.status === "running"}
            onClick={() => void run(async () => (actions.replaceTable(await patchTable(t.id, { saved: true })), toast.success("드라이브에 정리한 데이터로 저장했습니다.", { position: "top-center" })), "저장하지 못했습니다.")}
            className={btn}
          >
            {t.saved ? <FolderCheck className="size-3.5 text-primary" aria-hidden /> : <FolderPlus className="size-3.5" aria-hidden />}
            {t.saved ? "저장됨" : "저장"}
          </button>
        )}
        <Menu
          label="내려받기"
          icon={Download}
          iconOnly
          disabled={!done}
          items={(note ? (["docx"] as const) : (["docx", "xlsx"] as const)).map((fmt) => ({ key: fmt, label: fmt === "docx" ? "Word (DOCX)" : "Excel (XLSX)", onClick: () => void run(() => downloadFile(tableExportPath(t.id, fmt), `${t.title}.${fmt}`), "내려받지 못했습니다.") }))}
        />
        {t.mine && !chart && !note && (
          <button
            type="button"
            title="행·열 바꾸기"
            aria-label="행·열 바꾸기"
            disabled={busy}
            onClick={() => void run(async () => actions.replaceTable(await patchTable(t.id, { orientation: t.spec.orientation === "items_as_rows" ? "subjects_as_rows" : "items_as_rows" })), "바꾸지 못했습니다.")}
            className={btn}
          >
            <ArrowLeftRight className="size-3.5" aria-hidden />
          </button>
        )}
      </div>
      <div className={cn("mt-1", inline && "thin-scrollbar max-h-[420px] overflow-auto")}>
        <AssetBlockView block={t.block} caption={false} />
      </div>
      {templating && <TemplateDialog table={t} onClose={() => setTemplating(false)} />}
    </div>
  );
}

export function AssetPanel() {
  const actions = useReportActions();
  const tables = useAtomValue(tablesAtom);
  const activeId = useAtomValue(activeTableIdAtom);
  const t = tables.find((x) => x.id === activeId) ?? tables[tables.length - 1];

  if (!t) return <p className="px-6 py-10 text-center text-[13px] text-text-secondary">만든 표·차트·메모가 여기 보입니다</p>;

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-4 pt-3 pb-8">
      {tables.length > 1 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {tables.map((x) => {
            const Icon = assetIcon(x);
            return (
              <button key={x.id} type="button" onClick={() => actions.setActiveTable(x.id)} className={cn("flex max-w-[200px] cursor-pointer items-center gap-1 rounded-full px-3 py-1 text-[12px] font-medium transition-colors", x.id === t.id ? "bg-primary-soft text-primary" : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200")}>
                <Icon className="size-3 shrink-0" aria-hidden />
                <span className="truncate">{x.title}</span>
              </button>
            );
          })}
        </div>
      )}
      <AssetCard key={t.id} t={t} />
    </div>
  );
}
