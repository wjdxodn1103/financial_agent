"use client";

/**
 * 워크스페이스 데이터 목록(사내 공용 + 워크스페이스) — 올리기·빼기 + 처리 중인 것이 있는 동안만 3초 폴링(이어 달리기).
 * 리포트 스튜디오는 자기 atom 으로 같은 API 를 쓴다(useDocumentJobs) — 이 훅은 워크스페이스 화면용.
 */
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { ApiError, getDocuments, removeDocument, uploadDocuments } from "../../report/api";
import type { DocumentCard, DocumentsPayload, IngestJob } from "../../report/types";

const MAX_POLLS = 200;

export function useWorkspaceDocuments(workspaceId: string, embedOn = true) {
  const [documents, setDocuments] = useState<DocumentCard[] | null>(null);
  const [jobs, setJobs] = useState<IngestJob[]>([]);
  const [uploading, setUploading] = useState(false);

  const apply = useCallback((d: DocumentsPayload) => {
    setDocuments(d.documents ?? []);
    setJobs(d.jobs ?? []);
  }, []);

  const refresh = useCallback(async () => {
    try {
      apply(await getDocuments(workspaceId));
    } catch {
      setDocuments((cur) => cur ?? []);
    }
  }, [apply, workspaceId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const activeKey = [
    ...jobs.filter((j) => j.status === "queued" || j.status === "processing").map((j) => j.id),
    ...(documents ?? []).filter((d) => (embedOn && !d.embedded) || d.enriching).map((d) => `${d.id}:${d.embedded}:${d.enriching}`),
  ].join(",");

  useEffect(() => {
    if (!activeKey) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let polls = 0;
    const tick = async () => {
      if (cancelled || ++polls > MAX_POLLS) return;
      await refresh();
      if (!cancelled) timer = setTimeout(() => void tick(), 3000);
    };
    timer = setTimeout(() => void tick(), 3000);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [activeKey, refresh]);

  const call = useCallback(
    async (fn: () => Promise<DocumentsPayload>, fail: string) => {
      try {
        const d = await fn();
        apply(d);
        if (d.errors?.length) toast.error(d.errors.join("\n"), { position: "top-center" });
      } catch (e) {
        toast.error(e instanceof ApiError && (e.status === 409 || e.status === 403) ? e.message : fail, { position: "top-center" });
      }
    },
    [apply],
  );

  const upload = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      setUploading(true);
      await call(() => uploadDocuments(workspaceId, files), "파일을 올리지 못했습니다.");
      setUploading(false);
    },
    [call, workspaceId],
  );

  const uploadVersion = useCallback(
    async (docId: string, file: File) => {
      setUploading(true);
      await call(() => uploadDocuments(workspaceId, [file], docId), "새 판을 올리지 못했습니다.");
      setUploading(false);
    },
    [call, workspaceId],
  );

  return {
    documents,
    jobs,
    uploading,
    refresh,
    upload,
    uploadVersion,
    remove: (docId: string) => call(() => removeDocument(workspaceId, { doc: docId }), "자료를 빼지 못했습니다."),
    dismissJob: (jobId: string) => call(() => removeDocument(workspaceId, { job: jobId }), "목록에서 지우지 못했습니다."),
  };
}
