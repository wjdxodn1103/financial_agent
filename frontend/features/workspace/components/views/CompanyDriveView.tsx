"use client";

/** 사내 공용 드라이브 — 회사가 미리 넣어 둔 데이터(읽기 전용). 'AI 참고'로 이 워크스페이스에서 쓸지 고르고, 누르면 오른쪽 미리보기. */
import { useState } from "react";
import { Building2, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError } from "../../../report/api";
import { FileTypeIcon, formatSize } from "../../../report/components/library/rows";
import { DocViewerBody } from "../../../report/components/viewer/DocViewerBody";
import type { DocumentCard } from "../../../report/types";
import { setDocumentEvidence } from "../../api";
import { useWorkspace } from "../../context";
import { useWorkspaceDocuments } from "../../hooks/useWorkspaceDocuments";

export function CompanyDriveView() {
  const ws = useWorkspace();
  const docs = useWorkspaceDocuments(ws.workspaceId, Boolean(ws.meta.provider.embed));
  const [preview, setPreview] = useState<DocumentCard | null>(null);
  const shared = (docs.documents ?? []).filter((d) => d.shared);
  const canEdit = ws.can("editor");

  const toggle = async (d: DocumentCard, use: boolean) => {
    try {
      await setDocumentEvidence(ws.workspaceId, d.id, use);
      await docs.refresh();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "바꾸지 못했습니다.", { position: "top-center" });
    }
  };

  return (
    <div className="flex min-h-0 flex-1">
      <section className="thin-scrollbar min-w-0 flex-1 overflow-y-auto bg-white px-8 pt-7 pb-12">
        <h1 className="flex items-center gap-2.5 text-[22px] font-bold tracking-tight text-text-primary">
          <Building2 className="size-6 text-primary" aria-hidden />
          사내 공용
        </h1>
        <div className="mt-6 grid grid-cols-[minmax(0,1fr)_96px_72px_76px] items-center gap-x-3 border-b border-neutral-100 px-3 pb-2 text-[12px] font-semibold text-neutral-500">
          <span>이름</span>
          <span>수정</span>
          <span>크기</span>
          <span>AI 참고</span>
        </div>
        {docs.documents === null && <p className="px-3 py-4 text-[14px] text-neutral-500">불러오는 중…</p>}
        {docs.documents !== null && shared.length === 0 && <p className="px-3 py-4 text-[14px] text-neutral-500">없음</p>}
        {shared.map((d) => (
          <div key={d.id} onClick={() => setPreview(d)} className={cn("grid cursor-pointer grid-cols-[minmax(0,1fr)_96px_72px_76px] items-center gap-x-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-neutral-50", preview?.id === d.id && "bg-primary-soft hover:bg-primary-soft")}>
            <span className="flex min-w-0 items-center gap-2.5">
              <FileTypeIcon type={d.fileType} />
              <span className={cn("truncate text-[14px] font-medium", d.excluded ? "text-neutral-400" : "text-text-primary")} title={d.fileName}>
                {d.label}
              </span>
            </span>
            <span className="text-[13px] text-neutral-600">{d.uploadedAt ? new Date(d.uploadedAt).toLocaleDateString("ko-KR", { month: "long", day: "numeric" }) : ""}</span>
            <span className="text-[13px] text-neutral-600">{formatSize(d.size)}</span>
            <span onClick={(e) => e.stopPropagation()}>
              <button type="button" role="switch" aria-checked={!d.excluded} aria-label={`${d.label} AI 참고`} disabled={!canEdit} onClick={() => void toggle(d, Boolean(d.excluded))} className={cn("relative h-6 w-10 cursor-pointer rounded-full transition-colors disabled:cursor-default disabled:opacity-50", !d.excluded ? "bg-primary" : "bg-neutral-300")}>
                <span className={cn("absolute top-0.5 size-5 rounded-full bg-white shadow transition-all", !d.excluded ? "left-[18px]" : "left-0.5")} />
              </button>
            </span>
          </div>
        ))}
      </section>
      {preview && (
        <aside className="flex w-[440px] shrink-0 flex-col border-l border-neutral-200 bg-white">
          <div className="flex justify-end border-b border-neutral-100 px-2 py-1">
            <button type="button" aria-label="닫기" onClick={() => setPreview(null)} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
              <X className="size-4" aria-hidden />
            </button>
          </div>
          <div className="min-h-0 flex-1">
            <DocViewerBody workspaceId={ws.workspaceId} doc={preview} />
          </div>
        </aside>
      )}
    </div>
  );
}
