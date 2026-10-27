"use client";

/**
 * 이 작업 채팅의 데이터 — 워크스페이스에서 AI 가 참고하는 데이터(사내 공용 + 워크스페이스) 가운데 이 작업에서 쓸 것을 켜고 끈다(작성자).
 * 줄을 누르면 "문서 보기" 탭에서 연다. 끌어다 놓거나 버튼으로 올리면 워크스페이스 데이터로 올라가고 이 작업에서 바로 켜진다.
 */
import { useState } from "react";
import { useAtomValue } from "jotai";
import { Loader2, Plus, Upload, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { DataScopePicker, toScope, type ScopeChoice } from "../../../workspace/components/DataScopePicker";
import { canChatAtom, dataScopeAtom, documentsAtom, jobsAtom, uploadingAtom, viewingDocAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import { FileTypeIcon, FolderRow, fileMeta } from "./rows";

/** 참고 데이터 범위 한 줄 — 기본값이면 '워크스페이스 기본값', 직접 골랐으면 폴더·데이터 수. 작성자는 '바꾸기'로 고른다 */
function ScopeLine({ canChat }: { canChat: boolean }) {
  const actions = useReportActions();
  const scope = useAtomValue(dataScopeAtom);
  const [editing, setEditing] = useState<ScopeChoice | null>(null);
  const [busy, setBusy] = useState(false);
  const custom = scope?.mode === "custom";
  const label = custom ? [scope.folders.length ? `폴더 ${scope.folders.length}` : "", scope.docs.length ? `데이터 ${scope.docs.length}` : ""].filter(Boolean).join(" · ") || "직접 고름" : "워크스페이스 기본값";
  const save = async () => {
    if (!editing) return;
    setBusy(true);
    if (await actions.setDataScope(toScope(editing))) setEditing(null);
    setBusy(false);
  };
  return (
    <>
      <div className="mx-1 mb-1 flex items-center justify-between gap-2 rounded-lg bg-neutral-50 px-2.5 py-1.5 text-xs">
        <span className="min-w-0 truncate text-text-secondary" title={custom ? [...scope.folders.map((f) => f.name), ...scope.docs.map((d) => d.label)].join(", ") : undefined}>
          참고 범위 · <span className="font-medium text-text-primary">{label}</span>
        </span>
        {canChat && (
          <button type="button" onClick={() => setEditing({ mode: scope?.mode ?? "default", docs: scope?.docs ?? [], folders: scope?.folders ?? [] })} className="shrink-0 cursor-pointer font-medium text-primary hover:underline">
            바꾸기
          </button>
        )}
      </div>
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={() => setEditing(null)}>
          <div onMouseDown={(e) => e.stopPropagation()} className="w-full max-w-[520px] rounded-[24px] bg-white p-6 shadow-xl">
            <h2 className="mb-4 text-[20px] font-bold tracking-tight text-text-primary">참고 데이터</h2>
            <DataScopePicker value={editing} onChange={setEditing} />
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" onClick={() => setEditing(null)} className="h-10 cursor-pointer rounded-xl bg-neutral-100 px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-200">
                취소
              </button>
              <button type="button" disabled={busy || (editing.mode === "custom" && !editing.docs.length && !editing.folders.length)} onClick={() => void save()} className="h-10 cursor-pointer rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40">
                저장
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export const ACCEPT = ".pdf,.docx,.xlsx,.xlsm,.txt,.md,.markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/plain,text/markdown";

export function DocumentsFolder() {
  const actions = useReportActions();
  const documents = useAtomValue(documentsAtom);
  const jobs = useAtomValue(jobsAtom);
  const uploading = useAtomValue(uploadingAtom);
  const viewing = useAtomValue(viewingDocAtom);
  const canChat = useAtomValue(canChatAtom);
  const [open, setOpen] = useState(true);
  const [over, setOver] = useState(false);

  const shown = jobs.filter((j) => j.status !== "done");
  const used = documents.filter((d) => !d.off).length;

  const pick = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = ACCEPT;
    input.onchange = () => void actions.uploadDocuments(input.files ? Array.from(input.files) : []);
    input.click();
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        void actions.uploadDocuments(Array.from(e.dataTransfer.files));
      }}
      className={cn("rounded-xl transition-colors", over && "bg-primary-soft ring-2 ring-primary-soft-border")}
    >
      <FolderRow open={open} label="이 작업의 데이터" count={documents.length} extra={documents.length ? `사용 ${used}` : uploading ? "올리는 중…" : undefined} onClick={() => setOpen((v) => !v)} />
      {open && (
        <div className="ml-3 flex flex-col">
          <ScopeLine canChat={canChat} />
          {documents.length === 0 && !shown.length && !uploading && (
            <button
              type="button"
              onClick={pick}
              className="mx-1 my-2 flex flex-col items-center gap-1.5 rounded-lg border border-dashed border-neutral-300 px-3 py-6 text-center text-xs text-text-secondary transition-colors hover:border-primary hover:text-primary"
            >
              <Upload className="size-5" aria-hidden />
              파일을 끌어다 놓거나 눌러서 올리기
              <span className="text-[11px]">PDF · DOCX · XLSX · TXT · MD</span>
            </button>
          )}

          {shown.map((j) => (
            <div key={j.id} className={cn("flex items-center gap-2 rounded-lg px-2 py-1.5", j.status === "error" ? "text-red-600" : "text-text-secondary")}>
              <FileTypeIcon type={j.fileName.split(".").pop() ?? ""} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm" title={j.fileName}>
                  {j.fileName}
                </span>
                <span className="flex items-center gap-1 truncate text-xs">
                  {j.status !== "error" && <Loader2 className="size-3 animate-spin" aria-hidden />}
                  {j.status === "error" ? `실패: ${j.error ?? ""}` : "처리 중"}
                </span>
              </span>
              {j.status === "error" && (
                <button type="button" title="목록에서 지우기" aria-label="목록에서 지우기" onClick={() => void actions.dismissJob(j.id)} className="shrink-0 cursor-pointer rounded p-1 hover:text-text-primary">
                  <X className="size-3.5" aria-hidden />
                </button>
              )}
            </div>
          ))}

          {documents.map((d) => (
            <div key={d.id} className={cn("flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors hover:bg-neutral-100", viewing?.docId === d.id && "bg-primary-soft hover:bg-primary-soft")}>
              <input
                type="checkbox"
                checked={!d.off}
                disabled={!canChat}
                onChange={(e) => void actions.setDataUse(d.id, e.target.checked)}
                aria-label={`${d.label} — 이 작업에서 사용`}
                title="이 작업에서 사용"
                className="size-3.5 shrink-0 cursor-pointer accent-primary disabled:cursor-default"
              />
              <button type="button" onClick={() => actions.openDocument(d.id)} className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left">
                <FileTypeIcon type={d.fileType} />
                <span className="min-w-0 flex-1">
                  <span className={cn("block truncate text-sm", d.off ? "text-text-secondary" : "text-text-primary")} title={d.fileName}>
                    {d.label}
                  </span>
                  <span className="block truncate text-xs text-text-secondary">{[d.shared ? "사내 공용" : "", fileMeta(d)].filter(Boolean).join(" · ")}</span>
                </span>
              </button>
            </div>
          ))}

          {(documents.length > 0 || shown.length > 0) && (
            <button
              type="button"
              disabled={uploading}
              onClick={pick}
              className="mx-1 my-2 flex cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-dashed border-neutral-300 px-3 py-2 text-xs text-text-secondary transition-colors hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus className="size-3.5" aria-hidden />
              {uploading ? "올리는 중…" : "올리기"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
