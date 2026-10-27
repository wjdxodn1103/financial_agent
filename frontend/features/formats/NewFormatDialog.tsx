"use client";

/**
 * 새 문서 양식 — 기본은 샘플(PDF·Word)을 올리면 AI 가 쪽마다 읽어(글자층 없는 PDF 도) 형식을 뽑는다: 섹션 틀·작성 안내·문체 + 표·차트 양식(구성·겉모양).
 * 분석이 끝나면 서버가 '등록 전' 양식을 만들고, 이 창은 그 양식을 양식 화면으로 연다 — 거기서 원본과 나란히 보며 고치고(직접·말로) 등록한다.
 * 분석은 서버 뒤에서(7쪽에 약 5분) — 창을 닫아도 이어지고, 끝나면 목록에 '등록 전'으로 보인다. '빈 양식으로 시작'도 있다.
 */
import { useEffect, useRef, useState } from "react";
import { FileUp, Loader2, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError } from "../report/api";
import { useWorkspace } from "../workspace/context";
import { getFormatImport, uploadFormatSample } from "./api";
import type { FormatImportState } from "./types";

function errText(e: unknown, fallback: string): string {
  return e instanceof ApiError && e.status < 500 ? e.message : fallback;
}

export function NewFormatDialog({ onClose, onBlank, onReady }: { onClose: () => void; onBlank: () => Promise<void>; onReady: (formatId: string) => void }) {
  const ws = useWorkspace();
  const [state, setState] = useState<FormatImportState | null>(null);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const analyzing = uploading || state?.status === "analyzing";

  // 분석 중이면 상태를 다시 묻고, 끝나면 등록 전 양식을 연다
  useEffect(() => {
    if (state?.status !== "analyzing") return;
    const t = setTimeout(() => {
      void getFormatImport(ws.workspaceId, state.id)
        .then((s) => {
          setState(s);
          if (s.status === "ready" && s.formatId) onReady(s.formatId);
        })
        .catch(() => undefined);
    }, 2500);
    return () => clearTimeout(t);
  }, [state, ws.workspaceId, onReady]);

  const upload = async (file: File) => {
    if (!/\.(pdf|docx)$/i.test(file.name)) {
      toast.error("Word(.docx)나 PDF 샘플을 올려 주세요.", { position: "top-center" });
      return;
    }
    setUploading(true);
    try {
      setState(await uploadFormatSample(ws.workspaceId, file));
    } catch (e) {
      toast.error(errText(e, "샘플을 올리지 못했습니다."), { position: "top-center" });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={() => !busy && onClose()}>
      <div onMouseDown={(e) => e.stopPropagation()} className="flex w-full max-w-[560px] flex-col overflow-hidden rounded-[24px] bg-white shadow-xl">
        <div className="flex items-start gap-3 px-6 pt-6 pb-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-[20px] font-bold tracking-tight text-text-primary">새 문서 양식</h2>
            {state && <p className="mt-1 truncate text-[13px] text-text-secondary">{state.name}</p>}
          </div>
          <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>

        <div className="px-6 pb-6">
          {!state && !uploading && (
            <>
              <label
                onDragOver={(e) => (e.preventDefault(), setDrag(true))}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDrag(false);
                  const f = e.dataTransfer.files?.[0];
                  if (f) void upload(f);
                }}
                className={cn("flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors", drag ? "border-primary bg-primary-soft/40" : "border-neutral-300 hover:border-primary")}
              >
                <FileUp className="size-8 text-primary" aria-hidden />
                <span className="text-[15px] font-semibold text-text-primary">샘플 문서 올리기 (PDF · Word)</span>
                <span className="text-[13px] text-text-secondary">AI 가 쪽마다 읽어 섹션 틀·문체와 표·차트의 구성·모양을 뽑습니다. 대상 이름·숫자 같은 내용은 빼고 형식만 남깁니다.</span>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,.docx"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (f) void upload(f);
                  }}
                />
              </label>
              <button type="button" disabled={busy} onClick={() => void (setBusy(true), onBlank().finally(() => setBusy(false)))} className="mt-3 cursor-pointer text-[13px] text-text-secondary underline-offset-2 hover:text-primary hover:underline">
                샘플 없이 빈 양식으로 시작
              </button>
            </>
          )}

          {analyzing && (
            <div className="flex flex-col items-center gap-2 py-12 text-center text-[14px] text-text-secondary">
              <Loader2 className="size-6 animate-spin text-primary" aria-hidden />
              {uploading ? "올리는 중" : state?.progress?.total ? (state.progress.done < state.progress.total ? `쪽을 읽는 중 ${state.progress.done}/${state.progress.total}` : "양식으로 묶는 중") : "샘플을 읽는 중"}
              <span className="text-[12px]">몇 분 걸립니다. 끝나면 양식 화면이 열리고, 거기서 원본과 비교해 고친 뒤 등록합니다.</span>
              <span className="text-[12px]">창을 닫아도 분석은 이어지고, 끝나면 목록에 &apos;등록 전&apos;으로 보입니다.</span>
            </div>
          )}

          {state?.status === "error" && (
            <div className="py-10 text-center">
              <p className="text-[14px] text-red-600">{state.error}</p>
              <button type="button" onClick={() => setState(null)} className="mt-3 rounded-xl bg-neutral-100 px-3.5 py-2 text-[13px] font-semibold text-neutral-700 hover:bg-neutral-200">
                다시 올리기
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
