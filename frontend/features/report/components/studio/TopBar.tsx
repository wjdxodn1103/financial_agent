"use client";

/**
 * 상단 바 — 왼쪽 = 데이터 설정 · 작업 불러오기 · 저장하기(TaskButtons), 오른쪽 = 양식 / 패널 토글(문서·데이터) / DOCX 내보내기.
 * 작업 이름은 위쪽 경로에 보인다. 문서가 없는 작업(대화만)은 양식·내보내기 버튼을 숨긴다. 모델은 backend/.env 가 정한다(화면에 안 보인다).
 */
import { useState } from "react";
import { useAtomValue } from "jotai";
import { Download, FileSpreadsheet, FileText, LayoutTemplate, Loader2, PanelRight, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { useWorkspace } from "../../../workspace/context";
import { downloadBlocksXlsx } from "../../api";
import { canChatAtom, exportingAtom, hasDocAtom, modesAtom, panelsAtom, reportAtom, sessionAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import { TaskButtons } from "./TaskButtons";

/** DOCX 양식 — 등록하면 양식의 제목이 섹션이 되고 내보내기가 원본 양식(글꼴·표지·머리글)에 채운다 */
function TemplateButton() {
  const actions = useReportActions();
  const hasDoc = useAtomValue(hasDocAtom);
  const modes = useAtomValue(modesAtom);
  const session = useAtomValue(sessionAtom);
  const canChat = useAtomValue(canChatAtom);
  const ws = useWorkspace();
  const tpl = session?.template;
  const format = ws.meta.reportTypes.find((t) => t.id === session?.reportType && t.kind === "format");
  const pick = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    input.onchange = () => {
      const f = input.files?.[0];
      if (f) void actions.setTemplate(f);
    };
    input.click();
  };
  if (format) {
    // 고정 양식 리포트 — 섹션·표·그림이 양식으로 정해져 있어 DOCX 양식 등록 대신 양식 이름을 보인다
    return (
      <span title={`고정 양식: ${format.title} — 표 ${format.tables ?? 0} · 그림 ${format.charts ?? 0}`} className="flex h-8 max-w-[220px] items-center gap-1 rounded-md border border-primary-soft-border bg-primary-soft px-2 text-[11px] text-primary-soft-foreground">
        <LayoutTemplate className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{format.title}</span>
      </span>
    );
  }
  if (tpl) {
    return (
      <span title={`DOCX 양식: ${tpl.name} — 내보내기가 이 양식에 채웁니다`} className="flex h-8 max-w-[200px] items-center gap-1 rounded-md border border-primary-soft-border bg-primary-soft px-2 text-[11px] text-primary-soft-foreground">
        <LayoutTemplate className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{tpl.name}</span>
        {canChat && (
          <button type="button" aria-label="양식 해제" title="양식 해제" onClick={() => window.confirm("양식을 해제할까요? 섹션은 그대로 남고 내보내기는 기본 서식이 됩니다.") && void actions.setTemplate(null)} className="cursor-pointer rounded p-0.5 hover:bg-white">
            <X className="size-3" aria-hidden />
          </button>
        )}
      </span>
    );
  }
  if (!canChat || !(hasDoc || modes.writing)) return null;
  return (
    <button type="button" onClick={pick} title="DOCX 양식 등록 — 양식의 제목이 섹션이 되고, 내보내기가 원본 양식에 채웁니다" className="flex h-8 cursor-pointer items-center gap-1 rounded-md border border-neutral-200 px-2 text-[11px] text-text-secondary hover:bg-neutral-50 hover:text-text-primary">
      <LayoutTemplate className="size-3.5" aria-hidden />
      <span className="hidden xl:inline">양식 등록</span>
    </button>
  );
}

/** 열 토글 두 개 — 문서 열 / 오른쪽 '데이터' 패널(데이터 설정·AI 가 쓴 근거) */
function PanelToggles() {
  const actions = useReportActions();
  const panels = useAtomValue(panelsAtom);
  const items = [
    { id: "report", label: "문서", icon: FileText, on: panels.reportOpen, onClick: () => actions.toggleReport() },
    { id: "right", label: "데이터", icon: PanelRight, on: panels.rightOpen, onClick: () => actions.toggleRightPanel() },
  ];
  return (
    <div className="flex items-center gap-0.5 rounded-lg border border-neutral-200 bg-neutral-50 p-0.5">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <button
            key={item.id}
            type="button"
            aria-pressed={item.on}
            title={item.label}
            onClick={item.onClick}
            className={cn(
              "flex h-7 cursor-pointer items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors",
              item.on ? "bg-white text-primary shadow-sm" : "text-text-secondary hover:text-text-primary",
            )}
          >
            <Icon className="size-3.5" aria-hidden />
            <span className="hidden lg:inline">{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export function TopBar() {
  const actions = useReportActions();
  const report = useAtomValue(reportAtom);
  const exporting = useAtomValue(exportingAtom);
  const session = useAtomValue(sessionAtom);
  const hasDoc = useAtomValue(hasDocAtom);
  const modes = useAtomValue(modesAtom);
  const ws = useWorkspace();
  const stats = report?.stats;
  const showDoc = hasDoc || modes.writing;
  // 고정 양식은 글을 쓰기 전에도 표·그림이 데이터에서 채워지므로 바로 내보낼 수 있다
  const isFormat = ws.meta.reportTypes.find((t) => t.id === session?.reportType)?.kind === "format";
  const [xlsxBusy, setXlsxBusy] = useState(false);
  const exportXlsx = async () => {
    if (!session) return;
    setXlsxBusy(true);
    try {
      await downloadBlocksXlsx(session.id);
    } catch {
      toast.error("표·그림 데이터를 내려받지 못했습니다.", { position: "top-center" });
    } finally {
      setXlsxBusy(false);
    }
  };

  return (
    <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-neutral-200 bg-white px-3">
      <TaskButtons />
      <div className="flex shrink-0 items-center gap-2">
        <TemplateButton />
        <PanelToggles />
        <button
          type="button"
          hidden={!showDoc}
          aria-label="DOCX 로 내보내기"
          title="DOCX 로 내보내기"
          disabled={exporting || (!stats?.written && !isFormat)}
          onClick={() => void actions.exportDocx()}
          className="flex size-8 cursor-pointer items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-neutral-100 hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40"
        >
          {exporting ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
        </button>
        {isFormat && (
          <button
            type="button"
            aria-label="표·그래프 데이터(XLSX)"
            title="표·그래프 데이터(XLSX) — 블록마다 시트, 그래프는 엑셀 차트"
            disabled={xlsxBusy}
            onClick={() => void exportXlsx()}
            className="flex size-8 cursor-pointer items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-neutral-100 hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40"
          >
            {xlsxBusy ? <Loader2 className="size-4 animate-spin" /> : <FileSpreadsheet className="size-4" />}
          </button>
        )}
      </div>
    </header>
  );
}
