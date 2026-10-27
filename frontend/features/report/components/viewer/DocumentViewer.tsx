"use client";

/**
 * 리포트 스튜디오의 "보기" 탭 — 고른 문서를 DocViewerBody 로 보여 준다(근거 탭·참고 자료에서 특정 문단으로 온다).
 * OP-FE AssetViewer 자리(분석 표·그림 → 문서 문단).
 */
import { memo } from "react";
import { useAtomValue } from "jotai";

import { useWorkspaceId } from "../../../workspace/context";
import { documentsAtom, viewingDocAtom } from "../../atoms";
import { useReportActions } from "../../hooks/useReportStudio";
import { DocViewerBody } from "./DocViewerBody";

export const DocumentViewer = memo(function DocumentViewer() {
  const actions = useReportActions();
  const workspaceId = useWorkspaceId();
  const viewing = useAtomValue(viewingDocAtom);
  const documents = useAtomValue(documentsAtom);
  const doc = documents.find((d) => d.id === viewing?.docId);

  if (!viewing || !doc) {
    return (
      <div className="flex flex-1 flex-col gap-2 px-4 py-6">
        {documents.map((d) => (
          <button key={d.id} type="button" onClick={() => actions.openDocument(d.id)} className="cursor-pointer truncate rounded-lg border border-neutral-200 px-3 py-2 text-left text-sm text-text-primary hover:bg-neutral-50">
            {d.label}
          </button>
        ))}
        {documents.length === 0 && <p className="text-xs text-text-secondary">데이터가 없습니다.</p>}
      </div>
    );
  }
  return <DocViewerBody workspaceId={workspaceId} doc={doc} focusChunk={viewing.chunk} focusCell={viewing.cell} tick={viewing.tick} />;
});
